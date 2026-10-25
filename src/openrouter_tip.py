"""One OpenRouter research call for an AI tip, with bounded web-search spend."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import httpx

from src.jobs import REPORTS


MODEL = "google/gemini-2.5-flash"
URL = "https://openrouter.ai/api/v1/chat/completions"
USAGE_PATH = REPORTS / "openrouter_usage.json"
_usage_lock = threading.Lock()


def research(prompt: str, api_key: str) -> dict:
    """Return the answer and its cited URLs; never make a second model request."""
    response = httpx.post(
        URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "openrouter:web_search", "parameters": {
                "engine": "parallel", "mode": "basic", "max_results": 6,
                "max_total_results": 18, "max_uses": 3,
            }}],
            "max_tool_calls": 3,
            "usage": {"include": True},
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    message = data["choices"][0]["message"]
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenRouter returned no text")
    usage = data.get("usage") or {}
    searches = (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
    urls = []
    for annotation in message.get("annotations") or []:
        if not isinstance(annotation, dict):
            continue
        citation = annotation.get("url_citation") or {}
        url = citation.get("url") if isinstance(citation, dict) else None
        if isinstance(url, str):
            urls.append(url)
    return {"text": content, "source_urls": sorted(set(urls)),
            "usage": usage, "searched": bool(searches),
            "model": data.get("model") or MODEL}


def record(kind: str, result: dict) -> None:
    """Track paid model calls and searches without storing prompts or API keys."""
    try:
        usage = result.get("usage") or {}
        day = datetime.now(timezone.utc).date().isoformat()
        with _usage_lock:
            try:
                history = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                history = {}
            entry = history.setdefault(day, {"calls": 0, "by_kind": {}})
            entry["calls"] += 1
            entry["by_kind"][kind] = entry["by_kind"].get(kind, 0) + 1
            for field in ("prompt_tokens", "completion_tokens"):
                entry[field] = entry.get(field, 0) + int(usage.get(field) or 0)
            searches = (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
            entry["web_search_requests"] = entry.get("web_search_requests", 0) + int(searches)
            if isinstance(usage.get("cost"), (int, float)):
                entry["cost_usd"] = entry.get("cost_usd", 0) + usage["cost"]
            REPORTS.mkdir(parents=True, exist_ok=True)
            USAGE_PATH.write_text(json.dumps(dict(sorted(history.items())[-60:]), indent=1) + "\n", encoding="utf-8")
    except Exception:
        pass


def load() -> dict:
    try:
        return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

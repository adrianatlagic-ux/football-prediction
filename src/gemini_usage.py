"""A per-day count of the server's Gemini calls and their tokens.

The Google bill only shows a total; this file says which part of the site
spent it. Kept in data/jobs (on the Fly volume) and served by /jobs/status.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from src.jobs import REPORTS

PATH = REPORTS / "gemini_usage.json"
KEEP_DAYS = 60
_lock = threading.Lock()


def _tokens(response) -> dict:
    usage = getattr(response, "usage_metadata", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_token_count", None) or 0,
        "output_tokens": getattr(usage, "candidates_token_count", None) or 0,
        "thinking_tokens": getattr(usage, "thoughts_token_count", None) or 0,
        "tool_tokens": getattr(usage, "tool_use_prompt_token_count", None) or 0,
    }


def record(kind: str, response, grounded: bool = False) -> None:
    """Count one answered call. Never raises: counting must not cost a pick."""
    try:
        day = datetime.now(timezone.utc).date().isoformat()
        with _lock:
            try:
                usage = json.loads(PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                usage = {}
            entry = usage.setdefault(day, {"calls": 0, "grounded_calls": 0, "by_kind": {}})
            entry["calls"] += 1
            entry["grounded_calls"] += int(grounded)
            entry["by_kind"][kind] = entry["by_kind"].get(kind, 0) + 1
            for field, count in _tokens(response).items():
                entry[field] = entry.get(field, 0) + count
            usage = dict(sorted(usage.items())[-KEEP_DAYS:])
            REPORTS.mkdir(parents=True, exist_ok=True)
            PATH.write_text(json.dumps(usage, indent=1) + "\n", encoding="utf-8")
    except Exception:
        pass


def load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

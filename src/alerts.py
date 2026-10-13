"""Alerts when a price source fails: the bet-at-home scraper, the Odds API.

A failed source used to show up only as a missing price on the page, and was
noticed hours later or not at all (bugs/2026-10-13-betathome-nur-siegquoten.md).
Each failure is written to data/logs/alerts.jsonl (on the Fly volume), at most
once per source, subject and day, and served at /alerts. A GitHub workflow
(.github/workflows/alerts.yml) reads /alerts and opens an issue for every new
one, so GitHub notifies the owner.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "logs" / "alerts.jsonl"
KEEP_DAYS = 14
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record(source: str, subject: str, message: str) -> bool:
    """Write an alert unless the same one was already written today.

    source  "bet-at-home" or "odds-api"; subject: what failed (a competition,
    "quota"); message: one German sentence for the owner. Returns whether it
    was new.
    """
    now = _now()
    ident = hashlib.sha1(f"{source}|{subject}|{now.date().isoformat()}".encode()).hexdigest()[:10]
    with _lock:
        if any(a["id"] == ident for a in recent(days=1)):
            return False
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            with PATH.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"id": ident, "at": now.isoformat(), "source": source,
                                         "subject": subject, "message": message}, ensure_ascii=False) + "\n")
        except OSError:
            return False
    return True


def recent(days: int = KEEP_DAYS) -> list:
    cutoff = (_now() - timedelta(days=days)).isoformat()
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            a = json.loads(line)
        except ValueError:
            continue
        if a.get("at", "") >= cutoff:
            out.append(a)
    return out

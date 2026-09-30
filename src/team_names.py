"""German display names for teams. Teams keep their English key everywhere
(fixtures, odds, colours); only text a visitor reads uses these. The frontend
reads the same file."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

NAMES_FILE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "team_names_de.json"


@lru_cache(maxsize=1)
def _names() -> dict:
    try:
        return json.loads(NAMES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def de_name(team: str) -> str:
    return _names().get(team, team)

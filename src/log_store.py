"""Where the bet and combo logs live: one file per competition.

    data/logs/
      README.md            what each file holds
      tips/<wettbewerb>.jsonl     one line per match: the three tips, short
      details/<wettbewerb>.jsonl  the same matches with everything logged
      combos/<wettbewerb>.jsonl   one line per combo ticket
      system/alerts.jsonl         price-source failures
      system/book_refresh.jsonl   every bet-at-home read
      archive/                    the original single-file logs, unchanged

The same layout is used on the Fly volume (the server writes it, see
src/scheduler.py) and in the repository (GitHub copies the server's files in,
scripts/pull_server_logs.py). Every reader goes through load_tips() and
load_combos() so no script needs to know the file names.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "data" / "logs"

# sport_key -> file name. Entries without a known competition go to "sonstige".
SLUGS = {
    "soccer_germany_bundesliga": "bundesliga",
    "soccer_uefa_champs_league": "champions-league",
    "soccer_uefa_nations_league": "nations-league",
    "soccer_fifa_world_cup": "wm-2026",
}
BY_NAME = {"Bundesliga": "bundesliga", "Champions League": "champions-league",
           "Nations League": "nations-league", "WM 2026": "wm-2026"}
OTHER = "sonstige"


def slug(entry: dict) -> str:
    """The competition file an entry belongs to (tips use sport_key and the
    competition name, combos use the sport key as "competition")."""
    for value in (entry.get("sport_key"), entry.get("competition")):
        if value in SLUGS:
            return SLUGS[value]
        if value in BY_NAME:
            return BY_NAME[value]
    return OTHER


def _dir(kind: str, logs: Path | None) -> Path:
    return (logs or LOGS) / kind


def files(kind: str, logs: Path | None = None) -> list[Path]:
    """Every log file of one kind ("tips" or "combos"), in a stable order."""
    folder = _dir(kind, logs)
    return sorted(folder.glob("*.jsonl")) if folder.is_dir() else []


def _read(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def load(kind: str, logs: Path | None = None) -> list[dict]:
    out = []
    for path in files(kind, logs):
        out.extend(_read(path))
    return out


def load_tips(logs: Path | None = None) -> list[dict]:
    """Every match with everything logged (details/), for grading and analysis."""
    return load("details", logs)


def load_combos(logs: Path | None = None) -> list[dict]:
    return load("combos", logs)


def _group(entries: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(slug(e), []).append(e)
    return groups


def _replace(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(temp, path)


_PICK = ("market", "outcome", "team", "best_odds", "bookmaker", "probability",
         "model_probability_raw", "market_probability")


def _pick(value):
    """A pick reduced to what a reader needs: the bet, its odds and probabilities."""
    if not isinstance(value, dict) or not value.get("market"):
        return None
    return {k: value[k] for k in _PICK if k in value}


def short(entry: dict) -> dict:
    """The readable line of a match: the three tips and nothing else.

    wett_tipp         the AI pick after the rules (tip, or withheld with the reason)
    modell_wahl       the model's likeliest outcome
    wahrscheinlichste_wette  the likeliest bet at odds 1.30-2.00 (🎯)
    """
    tip = dict(entry.get("bet_tip") or {})
    wett = {"status": tip.get("status"), "confirmed": tip.get("confirmed"),
            "tip": _pick(tip.get("tip")), "withheld": _pick(tip.get("withheld"))}
    for key in ("change", "change_reason", "model_agrees", "is_fallback", "fallback_reason"):
        if tip.get(key) not in (None, ""):
            wett[key] = tip[key]
    for key in ("first_pick", "original_pick"):
        if _pick(tip.get(key)):
            wett[key] = _pick(tip[key])
    return {
        "home_team": entry.get("home_team"), "away_team": entry.get("away_team"),
        "commence_time": entry.get("commence_time"), "competition": entry.get("competition"),
        "logged_at": entry.get("logged_at"),
        "wett_tipp": wett,
        "modell_wahl": _pick(entry.get("model_favorite")),
        "wahrscheinlichste_wette": _pick(entry.get("likely_pick")),
    }


def write_tips(entries: list[dict], logs: Path | None = None) -> None:
    """Rewrite the tip files from the full list of entries: the readable one
    (tips/) and the one with everything logged (details/)."""
    for name, group in _group(entries).items():
        _replace(_dir("details", logs) / f"{name}.jsonl", group)
        _replace(_dir("tips", logs) / f"{name}.jsonl", [short(e) for e in group])


def append_combos(entries: list[dict], logs: Path | None = None) -> None:
    for name, group in _group(entries).items():
        path = _dir("combos", logs) / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for e in group:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")


def system_path(name: str, logs: Path | None = None) -> Path:
    return (logs or LOGS) / "system" / name


def archive_path(name: str, logs: Path | None = None) -> Path:
    return (logs or LOGS) / "archive" / name


def as_text(kind: str, logs: Path | None = None) -> str:
    """All lines of one kind, for the /logs endpoint."""
    return "".join(p.read_text(encoding="utf-8") for p in files(kind, logs))

"""Where the bet and combo logs live: one file per competition.

    data/logs/
      README.md            what each file holds
      tips/<wettbewerb>.jsonl     one line per match: the three tips and the rest
      combos/<wettbewerb>.jsonl   one line per combo ticket
      memory/<wettbewerb>.jsonl   the AI's reviewed past tips (src/match_memory.py)
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
    return load("tips", logs)


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


# The columns of a tip line, in the order they are written: the match, the three
# tips (Wett-Tipp = bet_tip, Modell-Wahl = model_favorite, wahrscheinlichste
# Wette = likely_pick), then how model and AI agree, the AI evaluation and the
# priced bets. Anything else follows.
COLUMNS = ("home_team", "away_team", "commence_time", "competition", "result", "logged_at",
           "bet_tip", "model_favorite", "likely_pick", "combined",
           "agent_eval", "agent_eval_shadow", "ai_review_history", "bets")

# Logged until 14 November, not wanted any more (scripts/migrate_logs.py removes them from old lines).
DROPPED = ("green_bets", "red_bets", "recommendation", "recommendation_warning", "safest_pick",
           "bet_tip_v1", "price_tip")


def ordered(entry: dict) -> dict:
    """The entry with its columns in the documented order."""
    out = {k: entry[k] for k in COLUMNS if k in entry}
    out.update({k: v for k, v in entry.items() if k not in out})
    return out


def norm(name: str) -> str:
    """A team name reduced to letters, accents folded (Mönchengladbach = Monchengladbach)."""
    import re
    import unicodedata
    n = name.lower().replace("ø", "o").replace("ł", "l").replace("đ", "d").replace("ß", "ss")
    n = unicodedata.normalize("NFKD", n)
    n = re.sub(r"\band\b", " ", n).replace("&", " ")
    n = re.sub(r"[^a-z]", "", n)
    return {"usa": "unitedstates"}.get(n, n)


_norm = norm


def match_key(home: str, away: str, commence_time) -> tuple:
    """Teams AND date: the same pairing can meet twice in a season."""
    return (_norm(home), _norm(away), str(commence_time)[:10])


def _is_final(result: dict) -> bool:
    """A finished match at its 90-minute score (never extra time or penalties)."""
    return bool(result.get("completed")) and result.get("home_score") is not None \
        and result.get("away_score") is not None and result.get("score_scope", "regulation") != "unverified"


def settle(entries: list[dict], results: list[dict], now=None, source: str = "espn") -> int:
    """Write the final score into every tip whose match is finished and has none yet.

    The results feed only covers the last few weeks, so the score is saved into
    the log once, as soon as it exists; the record no longer depends on the
    feed still knowing the match. Returns how many entries were settled."""
    from datetime import datetime, timezone
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    finals = {match_key(r["home_team"], r["away_team"], r.get("commence_time")): r
              for r in results if _is_final(r)}
    settled = 0
    for e in entries:
        if e.get("result"):
            continue
        r = finals.get(match_key(e.get("home_team", ""), e.get("away_team", ""), e.get("commence_time")))
        if r is None:
            continue
        e["result"] = {"home_score": int(r["home_score"]), "away_score": int(r["away_score"]),
                       "source": source, "settled_at": stamp}
        settled += 1
    return settled


def unsettled(entries: list[dict], now) -> list[dict]:
    """Entries without a score whose match should be over (kickoff more than 2 h ago)."""
    from datetime import datetime, timedelta
    out = []
    for e in entries:
        if e.get("result"):
            continue
        try:
            kickoff = datetime.fromisoformat(str(e.get("commence_time")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if kickoff < now - timedelta(hours=2):
            out.append(e)
    return out


def finished_map(entries: list[dict], results: list[dict]) -> dict:
    """The finished matches for grading: the live feed plus every score saved in the log."""
    out = {match_key(r["home_team"], r["away_team"], r.get("commence_time")): r
           for r in results if r.get("completed") and r.get("home_score") is not None}
    for e in entries:
        r = e.get("result")
        if r:
            out.setdefault(match_key(e["home_team"], e["away_team"], e.get("commence_time")),
                           {"home_team": e["home_team"], "away_team": e["away_team"], "completed": True,
                            "home_score": r["home_score"], "away_score": r["away_score"]})
    return out


def write_tips(entries: list[dict], logs: Path | None = None) -> None:
    """Rewrite the tip files (one per competition) from the full list of entries."""
    for name, group in _group(entries).items():
        _replace(_dir("tips", logs) / f"{name}.jsonl", [ordered(e) for e in group])


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

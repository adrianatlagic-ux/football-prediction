"""How the AI tip of a finished match turned out, for the result card.

The tip, its odds and its reasoning come from the tip log (the line written
before kickoff), the final score from the same line; every priced bet of the
match is graded so the page can show which ones came in; the explanation
comes from the AI's memory case (src/match_memory.py), written the morning
after the match.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from src import log_store, match_memory

# The frontend's fixture lists and the odds feed spell some teams differently
# ("Bosnia-Herzegovina" / "Bosnia & Herzegovina") and date by local kickoff.


def _same(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))


def find_entry(entries: list[dict], home: str, away: str, day: str) -> Optional[dict]:
    """The log line of this match: both teams and a kickoff within a day of `day`."""
    try:
        d = date.fromisoformat(day[:10])
    except ValueError:
        return None
    days = {(d + timedelta(n)).isoformat() for n in (-1, 0, 1)}
    h, a = log_store.norm(home), log_store.norm(away)
    for e in entries:
        if (str(e.get("commence_time"))[:10] in days and _same(log_store.norm(e.get("home_team", "")), h)
                and _same(log_store.norm(e.get("away_team", "")), a)):
            return e
    return None


def _graded_bets(entry: dict, names: dict) -> list[dict]:
    """Every priced bet once (best odds), with whether it came in."""
    bets = entry.get("bets") or ((entry.get("agent_eval") or {}).get("research_input") or {}).get("candidates") or []
    best: dict[tuple, dict] = {}
    for b in bets:
        if not b.get("market") or not isinstance(b.get("best_odds"), (int, float)):
            continue
        key = (b["market"], b.get("outcome"), b.get("team"))
        if key not in best or b["best_odds"] > best[key]["best_odds"]:
            best[key] = b
    likely = entry.get("likely_pick") or {}
    is_likely = lambda b: (b["market"], b.get("outcome"), b.get("team")) == (
        likely.get("market"), likely.get("outcome"), likely.get("team"))
    out = []
    for b in best.values():
        outcome = match_memory._grade(b, entry)
        if outcome is None:
            continue
        out.append({"market": b["market"], "outcome": b.get("outcome"), "team": names.get(b.get("team"), b.get("team")),
                    "best_odds": b["best_odds"], "market_probability": b.get("market_probability"),
                    "likely": is_likely(b), "result": outcome})
    return sorted(out, key=lambda b: -(b.get("market_probability") or 0))


def tip_result(home: str, away: str, day: str, entries: Optional[list[dict]] = None,
               cases: Optional[list[dict]] = None) -> dict:
    entries = log_store.load_tips() if entries is None else entries
    entry = find_entry(entries, home, away, day)
    if not entry or not entry.get("result"):
        return {"found": False}
    a = entry.get("agent_eval") or {}
    pick = a.get("pick") or a.get("selected_pick")
    cases = match_memory.load_cases() if cases is None else cases
    # The page's own spelling of the teams, so it finds their flags and German names.
    names = {entry["home_team"]: home, entry["away_team"]: away}
    case = next((c for c in cases if c.get("id") == match_memory.case_id(entry)), None)
    return {
        "found": True,
        "home_team": home, "away_team": away,
        "score": {"home": entry["result"]["home_score"], "away": entry["result"]["away_score"]},
        "tip": pick and {
            "market": pick["market"], "outcome": pick.get("outcome"), "team": names.get(pick.get("team"), pick.get("team")),
            "best_odds": pick.get("best_odds"), "market_probability": pick.get("market_probability"),
            "headline": a.get("bet_headline") or "", "reasoning": a.get("bet_reasoning") or "",
            "result": match_memory._grade(pick, entry),
        },
        "bets": _graded_bets(entry, names),
        "review": case and {
            "what_decided": case.get("what_decided", ""), "how_it_went": case.get("how_it_went", ""),
            "luck_or_reasoning": case.get("luck_or_reasoning", ""),
            "luck_explanation": case.get("luck_explanation", ""),
            "arguments": [{"argument": x.get("argument"), "came_true": x.get("came_true"), "why": x.get("why")}
                          for x in case.get("arguments", [])],
        },
    }

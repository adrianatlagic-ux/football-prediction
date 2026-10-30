"""Quoted market candidates and coverage for one research-only AI call."""

import math
from datetime import datetime, timezone

VERSION = "market_research_only_v5"


def fresh_candidates(vb):
    """Give the AI every supported, fresh, priced outcome in stable order."""
    bets = []
    for bet in vb.get("bets", []):
        odds = bet.get("best_odds")
        market = bet.get("market", "")
        if (market == "1X2" or market == "BTTS" or market.startswith("Handicap ")
                or market.startswith("Over/Under ")):
            if ((bet.get("quote_fresh") is True or bet.get("quote_carried_forward") is True) and isinstance(odds, (int, float))
                    and not isinstance(odds, bool) and math.isfinite(odds) and odds > 1):
                bets.append(bet)
    return sorted(bets, key=lambda b: (b["market"], b.get("team") or b["outcome"], -b["best_odds"]))


def coverage(candidates):
    h2h = {b["outcome"] for b in candidates if b["market"] == "1X2"}
    totals, handicap_teams = {}, set()
    for bet in candidates:
        market = bet["market"]
        if market.startswith("Over/Under "):
            totals.setdefault(market, set()).add(bet["outcome"])
        elif market.startswith("Handicap ") and bet.get("team"):
            handicap_teams.add(bet["team"])
    available = {
        "1X2": {"home_win", "draw", "away_win"} <= h2h,
        "Handicap": len(handicap_teams) >= 2,
        "Over/Under": any({"Over", "Under"} <= sides for sides in totals.values()),
        "BTTS": {"yes", "no"} <= {b["outcome"].lower() for b in candidates if b["market"] == "BTTS"},
    }
    missing = [name for name in ("1X2", "Handicap", "Over/Under") if not available[name]]
    return {"complete": not missing, "missing_main_markets": missing, "available": available}


def input_snapshot(vb, candidates, now=None):
    now = now or datetime.now(timezone.utc)
    return {"version": VERSION, "at": now.isoformat(), "sport_key": vb.get("sport_key"),
            "event_id": vb.get("event_id"), "commence_time": vb.get("commence_time"),
            "odds_fetched_at": vb.get("odds_fetched_at"), "odds_stage": vb.get("odds_stage"),
            "coverage": coverage(candidates),
            "candidates": [{k: bet.get(k) for k in ("market", "outcome", "team", "best_odds",
                            "bookmaker", "quote_last_update", "quote_carried_forward", "odds_fetched_at")}
                           for bet in candidates]}


def market_changes(previous, current):
    """Summarize quote changes for the single scheduled re-check prompt."""
    if not previous:
        return None
    def index(snapshot):
        return {(bet["market"], bet["outcome"], bet.get("team")): bet["best_odds"]
                for bet in snapshot.get("candidates", [])}
    old, new = index(previous), index(current)
    label = lambda key: f"{key[0]} / {key[2] or key[1]}"
    return {
        "added": [f"{label(key)} @{new[key]}" for key in sorted(new.keys() - old.keys(), key=str)],
        "removed": [f"{label(key)} @{old[key]}" for key in sorted(old.keys() - new.keys(), key=str)],
        "changed": [f"{label(key)} {old[key]} -> {new[key]}" for key in sorted(old.keys() & new.keys(), key=str)
                    if old[key] != new[key]],
    }

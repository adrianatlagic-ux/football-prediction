"""Fresh market candidates, coverage and compact model context for one AI call."""

import math
from datetime import datetime, timezone

VERSION = "full_market_model_context_v4"


def fresh_candidates(vb):
    """Give the AI every supported, fresh, priced outcome in stable order."""
    bets = []
    for bet in vb.get("bets", []):
        odds = bet.get("best_odds")
        market = bet.get("market", "")
        if (market == "1X2" or market == "BTTS" or market.startswith("Handicap ")
                or market.startswith("Over/Under ")):
            if (bet.get("quote_fresh") is True and isinstance(odds, (int, float))
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


def model_context(prediction):
    """Give the agent the readable outputs of the whole quantitative analysis.

    The score matrix itself is intentionally omitted: it is a large, redundant
    representation of the market probabilities already included below.
    """
    result = {}
    for key in ("probability_home_win", "probability_draw", "probability_away_win"):
        value = prediction.get(key)
        if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
            result[key] = value
    score = prediction.get("score_prediction") or {}
    for key in ("home_xg", "away_xg"):
        value = score.get(key)
        if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
            result[key] = value
    if score.get("most_likely_score"):
        result["most_likely_score"] = score["most_likely_score"]
    if isinstance(score.get("top_scorelines"), list):
        result["top_scorelines"] = [
            {"score": row.get("score"), "probability": row.get("probability")}
            for row in score["top_scorelines"][:5]
            if isinstance(row, dict) and row.get("score") is not None
        ]
    if isinstance(score.get("betting_markets"), dict):
        result["market_probabilities"] = {
            key: value for key, value in score["betting_markets"].items()
            if key in {"over_under", "btts", "win_margin", "double_chance"}
        }
    if isinstance(prediction.get("explanation"), dict):
        result["team_indicators"] = prediction["explanation"]
    return result


def input_snapshot(vb, candidates, prediction=None, now=None):
    now = now or datetime.now(timezone.utc)
    return {"version": VERSION, "at": now.isoformat(), "sport_key": vb.get("sport_key"),
            "event_id": vb.get("event_id"), "commence_time": vb.get("commence_time"),
            "odds_fetched_at": vb.get("odds_fetched_at"), "odds_stage": vb.get("odds_stage"),
            "coverage": coverage(candidates), "model_context": model_context(prediction or {}),
            "candidates": [{k: bet.get(k) for k in ("market", "outcome", "team", "best_odds",
                            "bookmaker", "quote_last_update", "odds_fetched_at")}
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

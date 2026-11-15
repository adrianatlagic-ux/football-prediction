"""Quoted market candidates, coverage and model context for one AI call."""

import math
from datetime import datetime, timezone

# v9: football reasoning instead of value hunting, model context back in,
# odds movements no longer fed to the re-check as news. The value framing of
# v6-v8 led to price-argued picks (37% hit, mostly handicaps), while picks
# where our model rated the outcome above the market returned +26% ROI.
# v10: v9 asked "how many goals are realistic" and to "evaluate alternatives"
# only in its head; it then picked Over 2.5 in 7 of 13 matches with the
# alternatives always left empty. v10 asks what is most predictable in the
# match and makes it write down 2-3 candidates from different markets with
# its own probability for each - logged, so its calibration can be checked.
VERSION = "football_research_model_v10"


def _number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def model_context(prediction):
    """The readable outputs of our quantitative model for one match.

    The score matrix is left out: it is a large, redundant form of the
    market probabilities included below.
    """
    result = {key: prediction[key] for key in ("probability_home_win", "probability_draw", "probability_away_win")
              if _number(prediction.get(key))}
    score = prediction.get("score_prediction") or {}
    result.update({key: score[key] for key in ("home_xg", "away_xg") if _number(score.get(key))})
    if score.get("most_likely_score"):
        result["most_likely_score"] = score["most_likely_score"]
    if isinstance(score.get("top_scorelines"), list):
        result["top_scorelines"] = [{"score": row.get("score"), "probability": row.get("probability")}
                                    for row in score["top_scorelines"][:5]
                                    if isinstance(row, dict) and row.get("score") is not None]
    if isinstance(prediction.get("explanation"), dict):
        result["team_indicators"] = prediction["explanation"]
    return result


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


def input_snapshot(vb, candidates, prediction=None, now=None):
    now = now or datetime.now(timezone.utc)
    likely = vb.get("likely_pick") or {}
    baseline = next((bet for bet in candidates if all(
        bet.get(key) == likely.get(key) for key in ("market", "outcome", "team"))), None) if likely else None
    if baseline is not None:
        probability = baseline.get("market_probability")
        if not isinstance(probability, (int, float)) or not math.isfinite(probability) or not 0 <= probability <= 1:
            baseline = None
    return {"version": VERSION, "at": now.isoformat(), "sport_key": vb.get("sport_key"),
            "event_id": vb.get("event_id"), "commence_time": vb.get("commence_time"),
            "odds_fetched_at": vb.get("odds_fetched_at"), "odds_stage": vb.get("odds_stage"),
            "coverage": coverage(candidates), "model_context": model_context(prediction or {}),
            "market_baseline": {k: baseline.get(k) for k in (
                "market", "outcome", "team", "best_odds", "market_probability",
                "quote_last_update", "quote_carried_forward")} if baseline else None,
            "candidates": [{k: bet.get(k) for k in ("market", "outcome", "team", "best_odds",
                            "bookmaker", "quote_last_update", "quote_carried_forward", "odds_fetched_at",
                            "model_probability_raw", "market_probability")}
                           for bet in candidates]}


def market_changes(previous, current):
    """Summarize quote changes between the two checks, for the log.

    Only added/removed markets reach the re-check prompt; price moves alone
    were read by the AI as a reason to pick (v6-v8) and are kept out."""
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

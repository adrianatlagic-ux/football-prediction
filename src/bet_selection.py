"""Versioned, deterministic paper strategies. No fitted profitability claims."""
import math
import statistics
from datetime import datetime, timezone
from .bet_audit import settlement, timestamp

POLICY_VERSION = "bet_selection_v2"
MAX_QUOTE_AGE_SECONDS = 1800


def same_bet(a, b):
    return bool(a and b and all(a.get(k) == b.get(k) for k in ("market", "outcome", "team")))


def quote_is_fresh(value, now=None):
    """Provider timestamp freshness at the supplied retrieval time."""
    try:
        age = ((now or datetime.now(timezone.utc)) - timestamp(value)).total_seconds()
        return 0 <= age <= MAX_QUOTE_AGE_SECONDS
    except (ValueError, TypeError):
        return False


def market_evidence(event, key, name, point=None, now=None, exclude_book=None):
    """Devig each complete same-book market, then average the book estimates.

    Never pair unrelated handicap lines or normalize incomplete markets.
    For push markets this is a conditional price signal, not P(profit).
    """
    estimates = {}
    for book in event.get("bookmakers", []):
        identity = book.get("key") or book.get("title")
        if not identity or identity == exclude_book:
            continue
        for market in book.get("markets", []):
            if market.get("key") != key or not quote_is_fresh(market.get("last_update") or book.get("last_update"), now):
                continue
            outcomes = market.get("outcomes", [])
            if key == "h2h":
                required = {event["home_team"], "Draw", event["away_team"]}
                group = [o for o in outcomes if o.get("name") in required]
            elif key == "totals":
                required = {"Over", "Under"}
                group = [o for o in outcomes if o.get("name") in required and o.get("point") == point]
            else:
                required = {event["home_team"], event["away_team"]}
                group = [o for o in outcomes if o.get("name") in required and o.get("point") == (point if o.get("name") == name else -point)]
            if len(group) != len(required) or {o["name"] for o in group} != required:
                continue
            prices = [float(o["price"]) for o in group]
            if any(not math.isfinite(p) or p <= 1 for p in prices):
                continue
            denominator = sum(1 / p for p in prices)
            selected = next((o for o in group if o["name"] == name), None)
            if selected:
                estimates[identity] = (1 / selected["price"]) / denominator
    values = list(estimates.values())
    return {"books": estimates, "book_count": len(values),
            "mean": statistics.mean(values) if values else None,
            "low": min(values) if values else None, "high": max(values) if values else None}


def market_consensus(event, key, name, point=None, now=None):
    return market_evidence(event, key, name, point, now)["mean"]


def price_bet(bet, prediction, fallback_probability):
    """EV and fractional Kelly from the *same* settlement as the later audit.

    Legacy caches can price 1X2, DC, DNB and half totals; other markets need
    the complete score matrix. A truncated top-five score list is not enough.
    """
    h, d, a = (float(prediction[k]) for k in ("probability_home_win", "probability_draw", "probability_away_win"))
    total = h + d + a
    if total <= 0 or any(not math.isfinite(p) or p < 0 for p in (h, d, a)):
        raise ValueError("Invalid H/D/A probabilities")
    h, d, a = h / total, d / total, a / total
    market = bet["market"]
    home, away = prediction["home_team"], prediction["away_team"]
    # H/D/A-equivalent bets stay exactly aligned to the classifier.
    if market == "1X2" or market in ("Handicap +0.5", "Handicap -0.5", "Handicap 0.0"):
        states = [(1, 0, h), (0, 0, d), (0, 1, a)]
    else:
        matrix = prediction.get("score_prediction", {}).get("score_matrix")
        if matrix is None:
            if not market.startswith("Over/Under ") or float(market.split()[-1]) % 1 != 0.5:
                raise ValueError("Full score distribution required for this market")
            p = float(fallback_probability)
            if not 0 <= p <= 1:
                raise ValueError("Invalid total probability")
            return payout_metrics([(bet["best_odds"] - 1, p), (-1, 1 - p)])
        states = [(i, j, float(p)) for i, row in enumerate(matrix) for j, p in enumerate(row)]
        if any(not math.isfinite(p) or p < 0 for _, _, p in states) or abs(sum(p for _, _, p in states) - 1) > 1e-6:
            raise ValueError("Invalid complete score distribution")
    distribution = [(settlement(bet, home, away, hs, aws)[1], p) for hs, aws, p in states if p > 0]
    return payout_metrics(distribution)


def payout_metrics(distribution):
    ev = sum(r * p for r, p in distribution)
    def derivative(f):
        return sum(p * r / (1 + f * r) for r, p in distribution)
    lo, hi = 0.0, 1 - 1e-9
    if ev > 0:
        for _ in range(70):
            mid = (lo + hi) / 2
            if derivative(mid) > 0:
                lo = mid
            else:
                hi = mid
    return {"expected_value": ev, "kelly_stake_pct": lo * 25,
            "probability": sum(p for r, p in distribution if r > 0),
            "push_probability": sum(p for r, p in distribution if r == 0),
            "loss_probability": sum(p for r, p in distribution if r < 0),
            "payout_distribution": [{"profit": r, "probability": p} for r, p in distribution],
            "pricing_version": "settlement_distribution_v1"}


def strategy_comparison(vb, agent_eval=None):
    bets = [b for b in vb.get("bets", []) if b.get("quote_fresh")]
    model = vb.get("model_favorite")
    ai = (agent_eval or {}).get("pick")
    # Resolve identity against today's quotes; never reuse an old agent price.
    ai = next((b for b in bets if same_bet(b, ai)), None)
    market = vb.get("market_favorite")
    value = vb.get("recommendation") if not vb.get("recommendation_warning") else None
    confirmed = value if same_bet(value, model) and same_bet(value, ai) else None
    # Fixed conservative baseline, NOT a confidence interval or learned edge.
    # Restricted to binary 1X2 so market probabilities mean the same thing.
    conservative = []
    for b in bets:
        if b["market"] != "1X2" or b.get("market_probability") is None:
            continue
        stressed_p = max(0.0, 0.5 * b["model_probability_raw"] + 0.5 * b["market_probability"] - 0.03)
        stressed_ev = stressed_p * b["best_odds"] - 1
        if stressed_ev > 0 and not b.get("suspicious"):
            conservative.append({**b, "strategy_probability": stressed_p, "strategy_expected_value": stressed_ev})
    conservative_pick = max(conservative, key=lambda b: b["strategy_expected_value"], default=None)
    strategies = {}
    for name, pick, reason in (
        ("market_favorite_v1", market, "No fresh, complete 1X2 market"),
        ("value_v1", value, "No candidate passed the fixed value filters"),
        ("value_model_ai_v1", confirmed, "Value, model choice and AI do not all agree"),
        ("market_model_stress_v1", conservative_pick, "No positive edge after fixed probability stress"),
    ):
        strategies[name] = {"pick": pick, "decision": "paper_bet" if pick else "no_bet",
                            "reason": None if pick else reason}
    return {"version": POLICY_VERSION, "mode": "paper_comparison", "strategies": strategies,
            "snapshot_stage": vb.get("odds_stage", "untracked"),
            "odds_fetched_at": vb.get("odds_fetched_at"),
            "parameters": {"quote_max_age_seconds_at_fetch": MAX_QUOTE_AGE_SECONDS,
                           "market_model_weights": [0.5, 0.5], "probability_stress": 0.03,
                           "value_min_quarter_kelly_pct": 1.0, "value_ev_ceiling": 0.25},
            "context_adjustment": "not_fitted_no_automatic_news_probability_adjustment"}


def combine(vb, agent_eval=None):
    from .game_pick import select_game_pick, VERSION
    comparison = strategy_comparison(vb, agent_eval)
    market = comparison["strategies"]["market_favorite_v1"]["pick"]
    decision = select_game_pick(vb)
    pick = decision["pick"]
    comparison["strategies"][VERSION] = {"pick": pick, "decision": decision["decision"], "reason": decision["reason"]}
    model, ai = vb.get("model_favorite"), (agent_eval or {}).get("pick")
    ai = next((b for b in vb.get("bets", []) if b.get("quote_fresh") and same_bet(b, ai)), None)
    ma, aa = same_bet(pick, model), same_bet(pick, ai)
    return {"market_favorite": market, "model_favorite": model, "agent_pick": ai,
            "value_pick": comparison["strategies"]["value_v1"]["pick"],
            "consensus_pick": pick, "selection": decision, "model_agrees": ma, "agent_agrees": aa,
            "agreement_count": int(ma) + int(aa), "strategy_comparison": comparison,
            "consensus_label": "Game Pick — passed the experimental price and stress checks" if pick else decision["reason"]}

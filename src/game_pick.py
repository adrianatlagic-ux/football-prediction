"""Price-sensitive selection under explicit stress assumptions, not a fitted CI.

The market-favorite baseline remains separate. All thresholds are versioned
experimental settings; prospective profitability has not been established.
"""
import math
from collections import Counter
from .bet_selection import payout_metrics

VERSION = "robust_game_pick_v1"
PARAMETERS = {"min_reference_books": 3, "model_weights": [0.25, 0.5, 0.75],
              "adverse_probability_mass": 0.03, "min_stressed_ev": 0.01,
              "max_paper_stake_fraction": 0.01, "max_model_market_gap": 0.20}


def aggregate(distribution):
    by_return = {}
    for r, p in distribution:
        by_return[r] = by_return.get(r, 0.0) + p
    return [(r, p) for r, p in sorted(by_return.items()) if p > 0]


def market_distribution(distribution, odds, q):
    """Match the reference fair-price probability, retaining model push mass.

    q is effective win-weight/(win-weight+loss-weight), not necessarily
    P(positive payout). Within win/loss categories the model shape is retained.
    Therefore push/quarter-market uncertainty is not fully market-observed.
    """
    pos = sum(p for r, p in distribution if r > 0)
    neg = sum(p for r, p in distribution if r < 0)
    if pos <= 0 or neg <= 0:
        raise ValueError("insufficient_payout_support")
    w = sum(p * r / (odds - 1) for r, p in distribution if r > 0) / pos
    loss = sum(-p * r for r, p in distribution if r < 0) / neg
    conditional_pos = q * loss / ((1 - q) * w + q * loss)
    target_pos = (pos + neg) * conditional_pos
    return [(r, p * (target_pos / pos if r > 0 else (pos + neg - target_pos) / neg if r < 0 else 1))
            for r, p in distribution]


def adverse_shift(distribution, mass):
    """Move up to mass from the largest returns into a full loss.

    This is a fixed sensitivity test, not a calibrated error probability.
    """
    remaining, shifted, out = mass, 0.0, []
    for r, p in sorted(distribution, reverse=True):
        moved = min(p, remaining) if r > -1 else 0
        remaining -= moved
        shifted += moved
        out.append((r, p - moved))
    return aggregate(out + [(-1.0, shifted)])


def assess(bet):
    identity = {k: bet.get(k) for k in ("market", "outcome", "team", "bookmaker")}
    excluded = lambda reason: {**identity, "eligible": False, "reason": reason}
    if not bet.get("quote_fresh"):
        return excluded("quote_not_valid_at_snapshot")
    reference = bet.get("selection_market_reference") or {}
    books = reference.get("books") or {}
    if len(books) < PARAMETERS["min_reference_books"]:
        return excluded("insufficient_reference_books")
    if bet.get("bookmaker_key") in books:
        return excluded("offered_book_in_reference")
    try:
        odds = float(bet["best_odds"])
        if not math.isfinite(odds) or odds <= 1:
            raise ValueError("invalid_odds")
        qvalues = [float(q) for q in books.values()]
        if any(not math.isfinite(q) or not 0 < q < 1 for q in qvalues):
            raise ValueError("invalid_market_reference")
        d = aggregate([(float(x["profit"]), float(x["probability"])) for x in bet["payout_distribution"]])
        # Validate before aggregation as well: negative mass must not cancel.
        if any(not math.isfinite(float(x["probability"])) or float(x["probability"]) < 0 for x in bet["payout_distribution"]):
            raise ValueError("invalid_payout_distribution")
        if abs(sum(p for _, p in d) - 1) > 1e-6 or any(not math.isfinite(r) or r < -1 or r > odds - 1 + 1e-8 for r, _ in d):
            raise ValueError("invalid_payout_distribution")
        w = sum(p*r/(odds-1) for r, p in d if r > 0)
        loss = sum(-p*r for r, p in d if r < 0)
        if w + loss <= 0:
            raise ValueError("insufficient_payout_support")
        model_q = w / (w + loss)
        mean_q = sum(qvalues) / len(qvalues)
        if abs(model_q - mean_q) > PARAMETERS["max_model_market_gap"]:
            return excluded("large_unvalidated_model_market_gap")
        scenarios = []
        for q in sorted(set([min(qvalues), mean_q, max(qvalues)])):
            reference_d = market_distribution(d, odds, q)
            for weight in PARAMETERS["model_weights"]:
                mixed = aggregate([(r, p * weight) for r, p in d] + [(r, p * (1-weight)) for r, p in reference_d])
                stressed = adverse_shift(mixed, PARAMETERS["adverse_probability_mass"])
                metrics = payout_metrics(stressed)
                scenarios.append((stressed, metrics, q, weight))
        worst_d, worst, _, _ = min(scenarios, key=lambda x: x[1]["expected_value"])
        stake = min(PARAMETERS["max_paper_stake_fraction"],
                    min(m["kelly_stake_pct"] / 100 for _, m, _, _ in scenarios))
        growth = min(sum(p * math.log1p(stake * r) for r, p in dist) for dist, _, _, _ in scenarios)
        floor_odds = max(1 + (sum(-p*r for r, p in dist if r < 0) + PARAMETERS["min_stressed_ev"]) /
                         sum(p*r/(odds-1) for r, p in dist if r > 0) for dist, _, _, _ in scenarios)
        eligible = worst["expected_value"] >= PARAMETERS["min_stressed_ev"] and growth > 0
        return {**identity, "eligible": eligible, "reason": "passed_stress_tests" if eligible else "no_edge_after_stress",
                "stressed_expected_value": worst["expected_value"], "ranking_score": growth,
                "paper_stake_pct": stake * 100, "min_acceptable_odds": math.ceil(floor_odds * 100) / 100,
                "model_expected_value": sum(r*p for r, p in d),
                "stressed_positive_payout_probability": worst["probability"],
                "reference_book_count": len(books), "reference_price_probability": mean_q,
                "reference_price_probability_range": [min(qvalues), max(qvalues)],
                "scenario_count": len(scenarios)}
    except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError) as exc:
        return excluded(str(exc) if isinstance(exc, ValueError) else "invalid_pricing_inputs")


def select_game_pick(vb):
    report = {"version": VERSION, "experimental": True, "parameters": PARAMETERS,
              "uncertainty_basis": "fixed_stress_assumptions_not_statistical_confidence_interval",
              "ai_probability_adjustment": False, "assessments": [], "pick": None}
    if not vb.get("snapshot_valid") or vb.get("in_play"):
        return {**report, "decision": "no_bet", "reason": "No valid pre-match odds snapshot."}
    candidates = []
    for bet in vb.get("bets", []):
        assessment = assess(bet)
        report["assessments"].append(assessment)
        if assessment["eligible"]:
            candidates.append((bet, assessment))
    if not candidates:
        counts = dict(Counter(a["reason"] for a in report["assessments"]))
        reason = "No bet has enough market data and a positive edge after the stress tests."
        if not report["assessments"]:
            reason = "No priced candidates are available in this odds snapshot."
        elif set(counts) == {"insufficient_reference_books"}:
            reason = "Each tip needs complete quotes from at least three other bookmakers; this snapshot has too few."
        elif set(counts) == {"no_edge_after_stress"}:
            reason = "No candidate retains at least 1% estimated return under every fixed stress scenario."
        return {**report, "decision": "no_bet", "exclusion_counts": counts, "reason": reason}
    # Reproducible ordering; no extra vote for market/model/AI agreement.
    bet, assessment = min(candidates, key=lambda x: (-x[1]["ranking_score"], -x[1]["stressed_expected_value"],
                                                   x[0]["market"], x[0].get("team") or x[0]["outcome"]))
    pick = {**bet, "selection_assessment": assessment}
    return {**report, "pick": pick, "decision": "paper_bet",
            "reason": "Highest worst-case modelled growth across the fixed stress scenarios; experimental, not proven profit."}

"""Accumulator ("Kombi") construction and honest scoring.

An accumulator only pays if EVERY leg wins, so its maths differ from the
single-bet case in three ways that matter, all of which this module makes
explicit rather than hiding behind one attractive combined-odds number:

1. Probabilities multiply ONLY if the legs are independent. Two bets on the
   same match are strongly dependent (a 3-0 home win settles both "home win"
   and "over 2.5"), so multiplying them would overstate the ticket's chance
   badly. We therefore allow at most one leg per fixture and never mix legs
   from the same match.
2. The bookmaker's margin compounds. Each leg is priced with an overround;
   an n-leg ticket carries roughly that margin n times over. That is the
   structural reason accumulators are usually worse value than singles, and
   we quantify it per ticket (`market_probability` vs `probability`) instead
   of asserting a combined edge without context.
3. Model error compounds multiplicatively too. If each leg is 3 percentage
   points overconfident, a four-leg ticket is far more than 12 points
   overconfident. The stress column applies a fixed per-leg haircut so the
   displayed edge is not the most flattering number available.

Ranking uses the Kelly growth fraction rather than raw expected value,
because EV alone would always prefer more legs (longer odds, higher EV, and
a hit rate approaching zero). Kelly balances the edge against the fact that
the entire stake is lost unless every leg lands.

None of this establishes that accumulators are profitable. They are offered
because they were requested; the scoring is designed to be honest about the
cost rather than to make the product look good.
"""
from itertools import combinations

# A leg below this model probability drags the whole ticket's hit rate down
# faster than its odds can compensate for. Not a tuned optimum - a guard.
MIN_LEG_PROBABILITY = 0.55
# Same evidence bar the single-bet selector uses: a price only one bookmaker
# quotes cannot be sanity-checked against the market, so it must not anchor a
# ticket either. The combination differs from /best-bets in what it OPTIMISES
# (hit rate over edge), never in how much it trusts a quote.
MIN_REFERENCE_BOOKS = 3
# Fixed per-leg confidence haircut for the stressed view. A sensitivity
# assumption, NOT a measured calibration error.
LEG_PROBABILITY_HAIRCUT = 0.03
MIN_LEGS = 2
MAX_LEGS = 4
# Accumulators are high variance; cap the suggested stake well under what
# Kelly alone would allow for a single bet.
MAX_STAKE_FRACTION = 0.02


def _product(values):
    total = 1.0
    for v in values:
        total *= v
    return total


def _has_market_reference(candidate):
    """Enough independent bookmakers to verify this price.

    `selection_market_reference` already excludes the book offering the bet,
    so this counts genuinely independent quotes. Candidates from an older
    pipeline without the field are rejected rather than silently trusted.
    """
    reference = candidate.get("selection_market_reference")
    if not isinstance(reference, dict):
        return False
    return reference.get("book_count", 0) >= MIN_REFERENCE_BOOKS


def leg_pool(value_bet_results):
    """Best eligible leg per fixture - at most one, to keep legs independent.

    `value_bet_results` is an iterable of (prediction, value_bets) pairs as
    produced by the existing /value-bets pipeline.
    """
    legs = []
    for prediction, vb in value_bet_results:
        if not vb.get("odds_found") or vb.get("in_play") or vb.get("exclusion"):
            continue
        candidates = vb.get("bets") or (vb.get("green_bets") or []) + (vb.get("red_bets") or [])
        eligible = [
            c for c in candidates
            if c.get("quote_fresh", True)
            and not c.get("suspicious")
            and not c.get("contradicts_favorite")
            and isinstance(c.get("probability"), (int, float))
            and isinstance(c.get("best_odds"), (int, float))
            and c["best_odds"] > 1
            and c["probability"] >= MIN_LEG_PROBABILITY
            and c.get("expected_value", 0) > 0
            and _has_market_reference(c)
        ]
        if not eligible:
            continue
        # Prefer the highest-probability leg, not the highest edge: in a
        # product, one shaky leg ruins every other leg's contribution, and
        # the biggest edges are exactly where the model is least trustworthy.
        best = max(eligible, key=lambda c: (c["probability"], c["expected_value"]))
        legs.append({
            "home_team": vb.get("home_team") or prediction.get("home_team"),
            "away_team": vb.get("away_team") or prediction.get("away_team"),
            "commence_time": vb.get("commence_time"),
            "sport_key": vb.get("sport_key"),
            "event_id": vb.get("event_id"),
            "market": best["market"],
            "outcome": best["outcome"],
            "team": best.get("team"),
            "best_odds": best["best_odds"],
            "bookmaker": best.get("bookmaker"),
            "probability": best["probability"],
            "market_probability": best.get("market_probability"),
            "expected_value": best.get("expected_value"),
        })
    return legs


def score_ticket(legs):
    """Combined odds/probability/edge for one candidate ticket."""
    odds = _product(l["best_odds"] for l in legs)
    probability = _product(l["probability"] for l in legs)
    stressed_probability = _product(
        max(0.0, l["probability"] - LEG_PROBABILITY_HAIRCUT) for l in legs
    )
    # Only meaningful when every leg has a market reference; a partial
    # product would silently compare different numbers of legs.
    market_probs = [l.get("market_probability") for l in legs]
    market_probability = (
        _product(market_probs) if all(isinstance(p, (int, float)) for p in market_probs) else None
    )
    expected_value = probability * odds - 1
    stressed_expected_value = stressed_probability * odds - 1
    kelly = (probability * odds - 1) / (odds - 1) if odds > 1 else 0.0
    stake_fraction = max(0.0, min(kelly, 1.0)) / 4
    return {
        "legs": legs,
        "leg_count": len(legs),
        "combined_odds": round(odds, 2),
        "probability": round(probability, 4),
        "stressed_probability": round(stressed_probability, 4),
        "market_probability": round(market_probability, 4) if market_probability is not None else None,
        # How much worse the combined price is than the combined model view;
        # this is where the compounded bookmaker margin becomes visible.
        "margin_cost": (
            round(probability - market_probability, 4) if market_probability is not None else None
        ),
        "expected_value": round(expected_value, 4),
        "stressed_expected_value": round(stressed_expected_value, 4),
        "kelly_fraction": round(kelly, 4),
        "stake_pct": round(min(stake_fraction, MAX_STAKE_FRACTION) * 100, 2),
        "returns_per_unit": round(odds - 1, 2),
    }


def build_tickets(legs, min_legs=MIN_LEGS, max_legs=MAX_LEGS, pool_size=7):
    """Score every ticket of an allowed size from the strongest legs.

    Only tickets that survive the stressed view are offered: an edge that
    disappears under a fixed 3-point-per-leg haircut is not robust enough to
    put a whole stake behind when a single wrong leg loses everything.
    """
    ranked = sorted(legs, key=lambda l: -l["probability"])[:pool_size]
    tickets = []
    for size in range(min_legs, min(max_legs, len(ranked)) + 1):
        for chosen in combinations(ranked, size):
            ticket = score_ticket(list(chosen))
            if ticket["stressed_expected_value"] <= 0:
                continue
            tickets.append(ticket)
    # Growth-optimal first: EV alone would always crown the longest ticket.
    tickets.sort(key=lambda t: (-t["kelly_fraction"], -t["probability"]))
    return tickets


def combo_report(value_bet_results, max_legs=MAX_LEGS):
    legs = leg_pool(value_bet_results)
    tickets = build_tickets(legs, max_legs=max_legs)
    return {
        "version": "combo_ticket_v1",
        "experimental": True,
        "eligible_legs": len(legs),
        "recommended": tickets[0] if tickets else None,
        "alternatives": tickets[1:4],
        "legs_considered": sorted(legs, key=lambda l: -l["probability"]),
        "parameters": {
            "min_leg_probability": MIN_LEG_PROBABILITY,
            "leg_probability_haircut": LEG_PROBABILITY_HAIRCUT,
            "max_legs": max_legs,
            "max_stake_fraction": MAX_STAKE_FRACTION,
            "one_leg_per_fixture": True,
        },
        "reason": None if tickets else (
            f"Only {len(legs)} fixture(s) currently offer a leg worth backing - "
            f"a combination needs at least {MIN_LEGS}, each from a different match."
            if len(legs) < MIN_LEGS else
            "No combination keeps a positive edge once each leg is stressed."
        ),
        "interpretation": (
            "Legs come from different matches so their probabilities can be multiplied. "
            "The bookmaker margin and any model overconfidence both compound with every "
            "added leg. Experimental, not proven profitable."
        ),
    }

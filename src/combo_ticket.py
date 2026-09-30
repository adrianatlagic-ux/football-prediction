"""Same-book, same-day accumulators of outcomes that are likely to happen.

What this does NOT claim is as important as what it does. It does not look for
value: every systematic attempt to find a betting edge in this project failed,
and random selection beat each rule on closing-line value, so a ticket sold as
"positive expected value" would be selling a measurement we could not make. It
picks the outcomes most likely to occur and says so.

Legs therefore need two things rather than an edge: our model must put them
above MIN_LEG_PROBABILITY, and the market must agree they are the likelier
side. That second condition is not decoration. Sorted into fifths by how far
the model departs from the price, the most confident fifth returned -1.62%
against the closing line and the least confident -0.61%: disagreement with the
market is anti-predictive here, so a leg the market disputes is a worse bet,
not a better one.

Independence is an explicit assumption, not a consequence of distinct games.
Push and split-settlement markets are excluded - a quarter line pays back half
a stake, which no accumulator arithmetic here accounts for.
"""
import math
from collections import defaultdict
from itertools import combinations, product
from zoneinfo import ZoneInfo
from .bet_audit import fixture_key, norm, timestamp

MIN_LEG_PROBABILITY = 0.55
# A leg the market prices as the underdog is rejected however much the model
# likes it; see the module docstring for why that disagreement is a red flag.
MIN_MARKET_AGREEMENT = 0.5
MIN_LEGS, MAX_LEGS = 2, 4
# A leg priced like a certainty (Under 6.5 at 1.01, Over 1.5 at 1.25) is
# always the likeliest bet of its match once a bookmaker lists every line.
# The floor is the page's "most likely" floor, so every leg of a combo is a
# bet that could stand as its match's 🎯 - the two never disagree.
MIN_LEG_ODDS = 1.30
# A combo exists to pay more than a single bet does. Ranking purely by how
# likely a ticket is to land walks straight to the shortest prices on the
# board - a first attempt returned a two-fold at 1.58, which is worse than
# simply backing one of its legs. So a ticket has to at least double the
# stake before it competes, and among those the likeliest one wins.
MIN_COMBINED_ODDS = 2.0
# A ticket just under the target is shown next to the chosen one when it is
# likelier: the user sees what the last bit of odds costs in hit chance.
NEAR_MISS_MIN_ODDS = 1.90
MAX_STAKE_FRACTION = 0.01


def _product(values):
    return math.prod(values)


def match_day(commence_time, tz="Europe/Berlin"):
    try:
        return timestamp(commence_time).astimezone(ZoneInfo(tz)).date().isoformat()
    except (ValueError, TypeError):
        return None


def binary_market(market):
    if market in ("1X2", "BTTS"):
        return True
    try:
        return market.startswith(("Handicap ", "Over/Under ")) and float(market.split()[-1]) % 1 == .5
    except (ValueError, TypeError, AttributeError):
        return False


def book_key(leg):
    return leg.get("bookmaker_key") or leg.get("bookmaker")


# The combo's leg rules. "market" is the one shown; "legacy_v3" is the rule
# before 26 September (the lower of model and market, the model had to rate
# a leg 55%, legs from 1.20, the model's ⚠ warnings excluded), still computed
# and logged beside it so the two can be compared on the same matches
# (scripts/log_combos.py, scripts/grade_combos.py).
POLICIES = {
    "market": {"min_odds": MIN_LEG_ODDS, "model_filters": False},
    "legacy_v3": {"min_odds": 1.20, "model_filters": True},
}


def leg_pool(value_bet_results, book=None, policy="market"):
    """Every qualifying leg, per bookmaker at that bookmaker's price.

    A match may contribute several legs (Over 1.5 and Team +0.5, say); the
    ticket search picks at most one of them. Choosing one per match up front
    hid combinations: the likeliest leg of a match can be too short to help a
    ticket reach its minimum odds while another leg of the same match fits.

    With `book`, only that bookmaker's prices are used - the one the user
    can actually bet with.
    """
    selected = {}
    for prediction, vb in value_bet_results:
        if not vb.get("odds_found") or not vb.get("snapshot_valid") or vb.get("in_play") or vb.get("exclusion"):
            continue
        try:
            identity = fixture_key(vb)
        except (KeyError, ValueError, TypeError):
            continue
        for candidate in vb.get("bets", []):
            if not binary_market(candidate.get("market")):
                continue
            # No model-based admission: high_deviation and contradicts_favorite
            # (the ⚠ warnings) used to exclude legs here, which let the model
            # veto bets the market rates likely. Selection is the market's; the
            # model is shown beside each leg for comparison only.
            rules = POLICIES[policy]
            if rules["model_filters"] and (candidate.get("high_deviation") or candidate.get("contradicts_favorite")):
                continue
            for offered in candidate.get("bookmaker_offers", [candidate]):
                if not book_key(offered) or not offered.get("quote_fresh"):
                    continue
                if book and book_key(offered) != book:
                    continue
                # Freshness (checked above) survives from the old stress test;
                # its reference-bookmaker requirement does not. That rule ruled
                # out 46 of 46 Nations League legs, because hardly anyone prices
                # Andorra or Liechtenstein completely - a rule that can only
                # ever produce tickets for the biggest fixtures is a rule
                # against small leagues, not against bad prices.
                # Legs are admitted and ranked by the market's estimate alone -
                # the same source as the page's 🎯, though the search may still
                # choose another leg of a match than its 🎯 when a different mix
                # reaches the minimum combined odds more likely. The model has
                # not been shown to be better calibrated than the market.
                if offered["best_odds"] < rules["min_odds"]:
                    continue
                market_probability = offered.get("market_probability")
                if rules["model_filters"]:
                    if (offered["probability"] < MIN_LEG_PROBABILITY or not isinstance(market_probability, (int, float))
                            or market_probability < MIN_MARKET_AGREEMENT):
                        continue
                    ranking = min(offered["probability"], market_probability)
                else:
                    if not isinstance(market_probability, (int, float)) or market_probability < MIN_LEG_PROBABILITY:
                        continue
                    ranking = market_probability
                leg = {**{k: offered.get(k) for k in ("market", "outcome", "team", "best_odds", "bookmaker", "bookmaker_key",
                       "probability", "market_probability", "expected_value", "quote_last_update")},
                       **{k: vb.get(k) for k in ("home_team", "away_team", "commence_time", "sport_key", "event_id", "odds_fetched_at", "odds_stage")},
                       # The ranking probability: the market's estimate, or
                       # under legacy_v3 the lower of model and market.
                       "conservative_probability": ranking, "policy": policy,
                       "market_agrees": True, "quote_fresh": True}
                key = (identity, book_key(leg), leg["market"], leg["outcome"], leg.get("team"))
                old = selected.get(key)
                if old is None or (leg["conservative_probability"], leg["probability"]) > (old["conservative_probability"], old["probability"]):
                    selected[key] = leg
    return list(selected.values())


def score_ticket(legs):
    if len(legs) < MIN_LEGS:
        raise ValueError("A ticket requires at least two fixtures")
    identities = [fixture_key(l) for l in legs]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate fixture on ticket")
    # Also reject repeated teams across distinct event IDs/times, a clear dependency.
    teams = [norm(l[k]) for l in legs for k in ("home_team", "away_team")]
    if len(set(teams)) != len(teams):
        raise ValueError("Repeated team on ticket")
    books, days = {book_key(l) for l in legs}, {match_day(l["commence_time"]) for l in legs}
    if None in books or len(books) != 1 or None in days or len(days) != 1:
        raise ValueError("Ticket needs one bookmaker and one matchday")
    if any(not binary_market(l.get("market")) for l in legs):
        raise ValueError("Push and split-settlement markets are not supported in combos")
    for l in legs:
        if not math.isfinite(l["best_odds"]) or l["best_odds"] <= 1 or not 0 <= l["probability"] <= 1:
            raise ValueError("Invalid odds or probability")
    odds = _product(l["best_odds"] for l in legs)
    probability = _product(l["probability"] for l in legs)
    cautious = [l["conservative_probability"] for l in legs]
    # Once the lower of model and market, the ranking probability is now the
    # market's; it may exceed the model's (market 65%, model 60%) and must not
    # be rejected for it - that check left two valid legs with no ticket.
    if any(not math.isfinite(p) or not 0 <= p <= 1 for p in cautious):
        raise ValueError("Invalid market probability")
    conservative_probability = _product(cautious)
    market_probs = [l.get("market_probability") for l in legs]
    market_probability = _product(market_probs) if all(isinstance(p, (int, float)) and 0 <= p <= 1 for p in market_probs) else None
    ev, conservative_ev = probability*odds-1, conservative_probability*odds-1
    # A flat stake: the returns here are not claimed to be positive, so sizing
    # by an edge we cannot measure would dress a guess up as a calculation.
    stake = MAX_STAKE_FRACTION
    return {"legs": legs, "leg_count": len(legs), "bookmaker": legs[0]["bookmaker"], "bookmaker_key": book_key(legs[0]),
            "combined_odds": round(odds, 2), "probability": round(probability, 4),
            "conservative_probability": round(conservative_probability, 4), "market_probability": market_probability,
            "model_market_gap": probability-market_probability if market_probability is not None else None,
            "expected_value": round(ev, 4), "conservative_expected_value": round(conservative_ev, 4),
            "stake_pct": round(stake*100, 2),
            # Ranked by how likely the whole ticket is to land, not by a
            # modelled edge - there is no edge to rank by.
            "ranking_score": conservative_probability,
            "returns_per_unit": round(odds-1, 2), "legs_the_market_agrees_with": sum(bool(l.get("market_agrees")) for l in legs),
            "independence_assumed": True, "offered_ticket_price_verified": False,
            "min_snapshot_time": min((l.get("odds_fetched_at") for l in legs if l.get("odds_fetched_at")), default=None)}


# Search bounds: the best few legs of each match and the best matches of a
# day. Wider than any day needs in practice and still small enough to try
# every combination (8 matches x 4 legs at 4-folds is ~18,000 tickets).
LEGS_PER_FIXTURE = 4
FIXTURES_PER_DAY = 8


def _by_fixture(group):
    fixtures = defaultdict(list)
    for leg in group:
        fixtures[fixture_key(leg)].append(leg)
    for legs in fixtures.values():
        legs.sort(key=lambda l: (-l.get("conservative_probability", l["probability"]), -l["best_odds"]))
    return fixtures


def build_tickets(legs, min_legs=MIN_LEGS, max_legs=MAX_LEGS, pool_size=FIXTURES_PER_DAY,
                  min_odds=MIN_COMBINED_ODDS):
    """Every ticket of one leg per match, same book and day, best first.

    All legs of a match stay candidates until the ticket is put together, so
    the search sees every mix and keeps the likeliest ticket that reaches
    MIN_COMBINED_ODDS - often with fewer legs, and so less margin paid.
    """
    groups = defaultdict(list)
    for leg in legs:
        groups[(book_key(leg), match_day(leg.get("commence_time")))].append(leg)
    tickets = []
    for group in groups.values():
        fixtures = _by_fixture(group)
        ranked = sorted(fixtures.values(), key=lambda ls: (-ls[0].get("conservative_probability", ls[0]["probability"]),
                                                           ls[0]["home_team"]))[:pool_size]
        for size in range(max(MIN_LEGS, min_legs), min(MAX_LEGS, max_legs, len(ranked))+1):
            for chosen in combinations(ranked, size):
                for picks in product(*(ls[:LEGS_PER_FIXTURE] for ls in chosen)):
                    if _product(l["best_odds"] for l in picks) < min_odds:
                        continue
                    try:
                        tickets.append(score_ticket(list(picks)))
                    except (ValueError, KeyError, TypeError):
                        continue
    return sorted(tickets, key=lambda t: (-t["ranking_score"], -t["conservative_probability"], t["bookmaker_key"]))


def day_reports(legs, max_legs=MAX_LEGS, all_days=(), started_by_day=None):
    by_day = defaultdict(list)
    for leg in legs:
        by_day[match_day(leg.get("commence_time"))].append(leg)
    for date in all_days:
        by_day[date]
    days = []
    for date in sorted(d for d in by_day if d):
        day_legs = by_day[date]
        with_near = build_tickets(day_legs, max_legs=max_legs, min_odds=NEAR_MISS_MIN_ODDS)
        # The exact product, not the rounded combined_odds: 1.33 x 1.50 is
        # 1.995 and must stay below 2.00.
        reaches = lambda t: _product(l["best_odds"] for l in t["legs"]) >= MIN_COMBINED_ODDS
        tickets = [t for t in with_near if reaches(t)]
        near = [t for t in with_near if not reaches(t)]
        top = tickets[0] if tickets else None
        all_in = None
        # Comparison uses only the recommended bookmaker, never mixed best prices.
        if top:
            # One leg per match: each match's likeliest.
            same_book = [ls[0] for ls in _by_fixture(
                [l for l in day_legs if book_key(l) == top["bookmaker_key"]]).values()]
            try:
                all_in = score_ticket(same_book)
            except (ValueError, KeyError, TypeError):
                pass
        started = (started_by_day or {}).get(date, 0)
        # Compare like with like: the best two-fold must not hide three-/four-folds.
        by_size = []
        for size in range(MIN_LEGS, min(max_legs, MAX_LEGS) + 1):
            ticket = next((t for t in tickets if t["leg_count"] == size), None)
            near_miss = next((t for t in near if t["leg_count"] == size), None)
            if ticket and near_miss and near_miss["ranking_score"] <= ticket["ranking_score"]:
                near_miss = None
            by_size.append({"leg_count": size, "ticket": ticket, "near_miss": near_miss,
                            "reason": None if ticket else (
                                f"Keine {size}er-Kombi möglich. Dafür braucht es {size} passende Spiele "
                                f"bei einem Buchmacher und eine Gesamtquote von mindestens {MIN_COMBINED_ODDS:.2f}.")})
        days.append({"date": date, "eligible_legs": len({fixture_key(l) for l in day_legs}),
                     "by_size": by_size,
                     "already_started": started, "recommended": top, "alternatives": tickets[1:3],
                     "all_in": all_in, "all_in_is_worse": bool(all_in and top and all_in["ranking_score"] < top["ranking_score"]),
                     "legs": day_legs,
                     "reason": None if top else f"Für diesen Tag gibt es keinen passenden Schein bei einem Buchmacher. {started} Spiele haben schon begonnen."})
    return days


def combo_report(value_bet_results, max_legs=MAX_LEGS, book=None, policy="market"):
    pairs = list(value_bet_results)
    legs = leg_pool(pairs, book=book, policy=policy)
    days, started = set(), defaultdict(int)
    for _, vb in pairs:
        date = match_day(vb.get("commence_time"))
        if date and vb.get("odds_found"):
            days.add(date)
            started[date] += bool(vb.get("in_play"))
    tickets = build_tickets(legs, max_legs=max_legs)
    return {"version": "combo_ticket_v3", "experimental": True,
            "eligible_legs": len({fixture_key(l) for l in legs}), "recommended": tickets[0] if tickets else None,
            "alternatives": tickets[1:4], "days": day_reports(legs, max_legs, days, started), "legs_considered": legs,
            "parameters": {"min_leg_probability": MIN_LEG_PROBABILITY, "max_legs": max_legs,
                           "max_stake_fraction": MAX_STAKE_FRACTION, "one_leg_per_fixture": True,
                           "same_bookmaker": True, "binary_settlement_only": True,
                           "single_bet_stress_required": False,
                           "ranking": "model_market_win_probability"},
            "reason": None if tickets else "Kein Schein mit Spielen eines Tages bei einem Buchmacher besteht alle Prüfungen. Märkte mit Rückerstattung und Viertel-Linien sind derzeit ausgeschlossen.",
            "interpretation": "Model estimate assuming independence between different fixtures; not guaranteed. Same-book singles prices multiplied, not a verified offered accumulator price. Experimental, no proven profitability."}


def price_tip_combos(entries, max_legs=MAX_LEGS):
    """Accumulators of the day's price tips - the only legs with a measured edge.

    Each entry is {"home_team", "away_team", "commence_time", "tip"} with a
    tip from src/price_tip.py. Legs are win-or-lose only (Draw No Bet refunds
    on a draw and is left out), one per match, same matchday; the best-edged
    MAX_LEGS of a day make its ticket. Probability and edge are judged by
    Pinnacle's fair prices, independence assumed as for every combo here.
    Price tips are rare - most days have fewer than two - so most days have
    no such ticket at all.
    """
    by_day = defaultdict(list)
    for e in entries:
        tip = e.get("tip") or {}
        if not tip or not binary_market(tip.get("market")):
            continue
        day = match_day(e.get("commence_time"))
        if day:
            by_day[day].append({**tip, **{k: e.get(k) for k in ("home_team", "away_team", "commence_time")}})
    out = []
    for day, legs in sorted(by_day.items()):
        legs = sorted(legs, key=lambda l: -l["edge"])[:max_legs]
        if len(legs) < MIN_LEGS:
            continue
        odds = _product(l["book_odds"] for l in legs)
        probability = _product(l["probability"] for l in legs)
        out.append({"date": day, "legs": legs, "leg_count": len(legs),
                    "combined_odds": round(odds, 2), "probability": round(probability, 4),
                    "edge": round(odds * probability - 1, 4), "stake_pct": round(MAX_STAKE_FRACTION * 100, 2)})
    return out

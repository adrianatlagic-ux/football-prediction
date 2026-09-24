"""Same-book, same-day experimental accumulators of binary-settlement legs.

Independence is an explicit assumption, not a consequence of distinct games.
Push/quarter markets are excluded until full accumulator settlement is supported.
"""
import math
from collections import defaultdict
from itertools import combinations
from zoneinfo import ZoneInfo
from .bet_audit import fixture_key, norm, timestamp
from .game_pick import assess

MIN_LEG_PROBABILITY = 0.55
MIN_LEGS, MAX_LEGS = 2, 4
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


def leg_pool(value_bet_results):
    """One qualifying leg per fixture AND bookmaker at that bookmaker's price."""
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
            for offered in candidate.get("bookmaker_offers", [candidate]):
                if not book_key(offered):
                    continue
                check = assess(offered)
                if not check.get("eligible") or offered["probability"] < MIN_LEG_PROBABILITY:
                    continue
                leg = {**{k: offered.get(k) for k in ("market", "outcome", "team", "best_odds", "bookmaker", "bookmaker_key",
                       "probability", "market_probability", "expected_value", "quote_last_update")},
                       **{k: vb.get(k) for k in ("home_team", "away_team", "commence_time", "sport_key", "event_id", "odds_fetched_at", "odds_stage")},
                       "stressed_probability": min(offered["probability"], check["stressed_positive_payout_probability"]),
                       "passes_single_bet_test": True, "selection_assessment": check}
                key = (identity, book_key(leg))
                old = selected.get(key)
                if old is None or (leg["stressed_probability"], leg["expected_value"]) > (old["stressed_probability"], old["expected_value"]):
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
    stressed = [l["stressed_probability"] for l in legs]
    if any(not math.isfinite(p) or not 0 <= p <= l["probability"] for l, p in zip(legs, stressed)):
        raise ValueError("Invalid stressed probability")
    stressed_probability = _product(stressed)
    market_probs = [l.get("market_probability") for l in legs]
    market_probability = _product(market_probs) if all(isinstance(p, (int, float)) and 0 <= p <= 1 for p in market_probs) else None
    ev, stressed_ev = probability*odds-1, stressed_probability*odds-1
    kelly = stressed_ev/(odds-1)
    stake = min(MAX_STAKE_FRACTION, max(0, kelly)/4)
    growth = stressed_probability*math.log1p(stake*(odds-1)) + (1-stressed_probability)*math.log1p(-stake)
    return {"legs": legs, "leg_count": len(legs), "bookmaker": legs[0]["bookmaker"], "bookmaker_key": book_key(legs[0]),
            "combined_odds": round(odds, 2), "probability": round(probability, 4),
            "stressed_probability": round(stressed_probability, 4), "market_probability": market_probability,
            "model_market_gap": probability-market_probability if market_probability is not None else None,
            "expected_value": round(ev, 4), "stressed_expected_value": round(stressed_ev, 4),
            "kelly_fraction": kelly, "stake_pct": round(stake*100, 2), "ranking_score": growth,
            "returns_per_unit": round(odds-1, 2), "legs_passing_single_bet_test": sum(bool(l.get("passes_single_bet_test")) for l in legs),
            "independence_assumed": True, "offered_ticket_price_verified": False,
            "min_snapshot_time": min((l.get("odds_fetched_at") for l in legs if l.get("odds_fetched_at")), default=None)}


def build_tickets(legs, min_legs=MIN_LEGS, max_legs=MAX_LEGS, pool_size=7):
    groups = defaultdict(list)
    for leg in legs:
        groups[(book_key(leg), match_day(leg.get("commence_time")))].append(leg)
    tickets = []
    for group in groups.values():
        ranked = sorted(group, key=lambda l: (-l.get("stressed_probability", l["probability"]), l["home_team"]))[:pool_size]
        for size in range(max(MIN_LEGS, min_legs), min(MAX_LEGS, max_legs, len(ranked))+1):
            for chosen in combinations(ranked, size):
                try:
                    ticket = score_ticket(list(chosen))
                except (ValueError, KeyError, TypeError):
                    continue
                if ticket["stressed_expected_value"] > 0:
                    tickets.append(ticket)
    return sorted(tickets, key=lambda t: (-t["ranking_score"], -t["stressed_probability"], t["bookmaker_key"]))


def day_reports(legs, max_legs=MAX_LEGS, all_days=(), started_by_day=None):
    by_day = defaultdict(list)
    for leg in legs:
        by_day[match_day(leg.get("commence_time"))].append(leg)
    for date in all_days:
        by_day[date]
    days = []
    for date in sorted(d for d in by_day if d):
        day_legs = by_day[date]
        tickets = build_tickets(day_legs, max_legs=max_legs)
        top = tickets[0] if tickets else None
        all_in = None
        # Comparison uses only the recommended bookmaker, never mixed best prices.
        if top:
            same_book = [l for l in day_legs if book_key(l) == top["bookmaker_key"]]
            try:
                all_in = score_ticket(same_book)
            except (ValueError, KeyError, TypeError):
                pass
        started = (started_by_day or {}).get(date, 0)
        days.append({"date": date, "eligible_legs": len({fixture_key(l) for l in day_legs}),
                     "already_started": started, "recommended": top, "alternatives": tickets[1:3],
                     "all_in": all_in, "all_in_is_worse": bool(all_in and top and all_in["ranking_score"] < top["ranking_score"]),
                     "legs": day_legs,
                     "reason": None if top else f"No qualifying same-book ticket for this day. {started} matches have already started."})
    return days


def combo_report(value_bet_results, max_legs=MAX_LEGS):
    pairs = list(value_bet_results)
    legs = leg_pool(pairs)
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
                           "same_bookmaker": True, "binary_settlement_only": True, "single_bet_stress_required": True},
            "reason": None if tickets else "No same-day ticket at one bookmaker passes all leg and ticket checks. Push/quarter markets are currently excluded.",
            "interpretation": "Model estimate assuming independence between different fixtures; not guaranteed. Same-book singles prices multiplied, not a verified offered accumulator price. Experimental, no proven profitability."}

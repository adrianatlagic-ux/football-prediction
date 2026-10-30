"""Scheduled odds snapshots: provider update time differs from fetch time."""
import math
from datetime import datetime, timezone, timedelta
from .bet_audit import timestamp

# 06:00 UTC, 08:00 in Germany: the morning read of the day's fixtures and
# bet-at-home's full market book, plus Odds API main-market prices.
# Final Odds API reads batch due fixtures by competition in the last hour.
DAILY_REFRESH_HOUR_UTC = 6


def stamp_event(event, fetched_at, stage):
    if stage not in ("initial", "daily", "final"):
        raise ValueError("Unknown odds snapshot stage")
    return {**event, "odds_fetched_at": fetched_at.isoformat(), "odds_stage": stage}


def _compact_market_history(event, books):
    """Keep at most the newest complete evidence per book, market and line.

    Carried offers and probability evidence have independent lifetimes: an
    offer survives until replaced, evidence until a newer complete group exists.
    """
    from .bet_selection import complete_market_groups
    for book in books:
        latest = {}
        for market in book["markets"]:
            carried = bool(market.get("carried_forward"))
            outcomes = (market.get("historical_outcomes", market.get("outcomes", []))
                        if carried else market.get("outcomes", []))
            updated = market.get("last_update") or book.get("last_update")
            try:
                rank = (timestamp(updated), not carried)
            except (ValueError, TypeError):
                continue
            for line, group in complete_market_groups(event, market.get("key"), outcomes).items():
                identity = (market["key"], line)
                if identity not in latest or rank > latest[identity][0]:
                    latest[identity] = (rank, market, group, updated)
        markets = []
        for market in book["markets"]:
            if market.get("carried_forward"):
                if not market.get("outcomes"):
                    continue
                # Quotes do not need to keep every historical market version.
                market = {**market, "historical_outcomes": []}
            markets.append(market)
        for _, market, group, updated in latest.values():
            if market.get("carried_forward"):
                markets.append({"key": market["key"], "last_update": updated,
                                "carried_forward": True, "outcomes": [],
                                "historical_outcomes": group})
        book["markets"] = markets


def _quotes_by_selection(event, as_of=None):
    """Index each bet by (market, outcome, line), with its current book offers."""
    from .bet_selection import quote_is_fresh
    fresh, carried = {}, {}
    for book in event.get("bookmakers", []):
        identity = book.get("key") or book.get("title")
        if not identity:
            continue
        for market in book.get("markets", []):
            updated = market.get("last_update") or book.get("last_update")
            is_carried = bool(market.get("carried_forward"))
            if as_of is not None and not is_carried and not quote_is_fresh(updated, as_of):
                continue
            try:
                observed = timestamp(updated)
            except (ValueError, TypeError):
                continue
            for outcome in market.get("outcomes", []):
                price = outcome.get("price")
                if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 1:
                    continue
                key = (market.get("key"), outcome.get("name"), outcome.get("point"))
                offers = (carried if is_carried else fresh).setdefault(key, {})
                prior = offers.get(identity)
                if prior and (observed, price) <= (timestamp(prior["last_update"]), prior["outcome"]["price"]):
                    continue
                offers[identity] = {"book": book, "outcome": outcome,
                                    "last_update": updated, "carried_forward": is_carried}
    # A newly fetched selection replaces every carried offer of that selection.
    return {**carried, **fresh}


def retain_missing_quotes(previous, current):
    """Upsert quotes by bet identity: replace fetched bets, keep absent bets.

    Match identity is checked first. Within a match the key is market, outcome
    and line; each value contains the bookmakers quoting it in the latest read.
    Probability evidence is retained independently of these available prices.
    """
    from .bet_selection import quote_is_fresh
    if any(previous.get(key) != current.get(key) for key in
           ("sport_key", "id", "home_team", "away_team", "commence_time")):
        return current
    try:
        previous_time = timestamp(previous["odds_fetched_at"])
    except (KeyError, TypeError, ValueError):
        return current

    quotes = {key: {identity: {**offer, "carried_forward": True}
                    for identity, offer in offers.items()}
              for key, offers in _quotes_by_selection(previous, previous_time).items()}
    quotes.update(_quotes_by_selection(current))

    # Adapt the map back to the provider format used by the table, AI and combos.
    books, markets = {}, {}
    for (market_key, _, _), offers in quotes.items():
        for identity, offer in offers.items():
            book = books.setdefault(identity, {**offer["book"], "markets": []})
            group = (identity, market_key, offer["last_update"], offer["carried_forward"])
            if group not in markets:
                markets[group] = {"key": market_key, "last_update": offer["last_update"],
                                  "carried_forward": offer["carried_forward"], "outcomes": []}
                if offer["carried_forward"]:
                    markets[group]["historical_outcomes"] = []
                book["markets"].append(markets[group])
            markets[group]["outcomes"].append(dict(offer["outcome"]))

    # Historical prices are evidence only; they never re-enter the quote map.
    for source, as_of in ((current, None), (previous, previous_time)):
        for old_book in source.get("bookmakers", []):
            identity = old_book.get("key") or old_book.get("title")
            if not identity:
                continue
            for market in old_book.get("markets", []):
                updated = market.get("last_update") or old_book.get("last_update")
                if as_of is not None and not market.get("carried_forward") and not quote_is_fresh(updated, as_of):
                    continue
                outcomes = (market.get("historical_outcomes", market.get("outcomes", []))
                            if market.get("carried_forward") else market.get("outcomes", []))
                if outcomes:
                    book = books.setdefault(identity, {**old_book, "markets": []})
                    book["markets"].append({"key": market.get("key"), "last_update": updated,
                                            "carried_forward": True, "outcomes": [],
                                            "historical_outcomes": outcomes})
    result = list(books.values())
    _compact_market_history(current, result)
    return {**current, "bookmakers": result}


def snapshot_context(event, now=None):
    now = now or datetime.now(timezone.utc)
    # Compatibility for callers supplying a fresh response directly.
    fetched = timestamp(event["odds_fetched_at"]) if event.get("odds_fetched_at") else now
    kickoff = timestamp(event["commence_time"])
    stage = event.get("odds_stage", "untracked")
    scheduled = fetched.replace(hour=DAILY_REFRESH_HOUR_UTC, minute=0, second=0, microsecond=0)
    if scheduled <= fetched:
        scheduled += timedelta(days=1)
    valid_until = kickoff if stage == "final" else min(kickoff, scheduled)
    return {"odds_fetched_at": fetched.isoformat(), "odds_stage": stage,
            "snapshot_valid_until": valid_until.isoformat(),
            "snapshot_valid": fetched <= now < valid_until,
            "calculated_at": now.isoformat(), "quote_basis": "scheduled_snapshot_not_live"}

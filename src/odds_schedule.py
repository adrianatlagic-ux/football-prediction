"""Scheduled odds snapshots: provider update time differs from fetch time."""
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


def retain_missing_quotes(previous, current):
    """Carry missing selections from the previous snapshot until kickoff.

    A selection seen in the new snapshot replaces all older offers for that
    selection, even if it is now quoted by a different bookmaker.
    """
    from .bet_selection import quote_is_fresh
    if any(previous.get(key) != current.get(key) for key in
           ("sport_key", "id", "home_team", "away_team", "commence_time")):
        return current
    try:
        previous_time = timestamp(previous["odds_fetched_at"])
    except (KeyError, TypeError, ValueError):
        return current
    books = [{**book, "markets": list(book.get("markets") or [])}
             for book in current.get("bookmakers", [])]
    available = {(market.get("key"), outcome.get("name"), outcome.get("point"))
                 for book in books for market in book.get("markets", [])
                 for outcome in market.get("outcomes", [])
                 if isinstance(outcome.get("price"), (int, float)) and outcome["price"] > 1}
    # Injection may pass through previously carried markets alongside new
    # offers. A replacement must also remove those already-carried prices.
    fresh_selections = {(market.get("key"), outcome.get("name"), outcome.get("point"))
                        for book in books for market in book.get("markets", [])
                        if not market.get("carried_forward")
                        for outcome in market.get("outcomes", [])
                        if isinstance(outcome.get("price"), (int, float)) and outcome["price"] > 1}
    for book in books:
        markets = []
        for market in book["markets"]:
            if market.get("carried_forward"):
                outcomes = [outcome for outcome in market.get("outcomes", [])
                            if (market.get("key"), outcome.get("name"), outcome.get("point"))
                            not in fresh_selections]
                if not outcomes and not market.get("historical_outcomes"):
                    continue
                market = {**market, "outcomes": outcomes}
            markets.append(market)
        book["markets"] = markets
    by_book = {book.get("key") or book.get("title"): book for book in books}
    for old_book in previous.get("bookmakers", []):
        identity = old_book.get("key") or old_book.get("title")
        if not identity:
            continue
        retained = []
        for market in old_book.get("markets", []):
            updated = market.get("last_update") or old_book.get("last_update")
            if not market.get("carried_forward") and not quote_is_fresh(updated, previous_time):
                continue
            missing = [outcome for outcome in market.get("outcomes", [])
                       if (market.get("key"), outcome.get("name"), outcome.get("point")) not in available]
            if market.get("historical_outcomes") or market.get("outcomes"):
                # Keep the original complete market only as probability evidence.
                # Its replaced prices must never become available offers again.
                retained.append({**market, "last_update": updated, "carried_forward": True,
                                 "outcomes": missing,
                                 "historical_outcomes": market.get("historical_outcomes", market.get("outcomes", []))})
        if retained:
            book = by_book.get(identity)
            if book is None:
                book = {**old_book, "markets": []}
                books.append(book)
                by_book[identity] = book
            book["markets"].extend(market for market in retained if market not in book["markets"])
    return {**current, "bookmakers": books}


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

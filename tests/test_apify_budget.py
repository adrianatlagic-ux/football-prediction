from src import apify_budget, book_odds


def test_a_run_must_fit_under_the_cap_minus_the_reserve(monkeypatch):
    monkeypatch.setattr(apify_budget, "usage", lambda token=None: {"used": 18.5, "limit": 21, "cycle_end": None})
    assert apify_budget.allows(1.0)          # 19.5 <= 20
    assert not apify_budget.allows(2.0)      # 20.5 > 20


def test_without_an_answer_from_apify_the_local_count_decides(monkeypatch):
    monkeypatch.setattr(apify_budget, "usage", lambda token=None: None)
    assert apify_budget.allows(100.0)


def test_the_morning_read_stops_at_the_account_cap(monkeypatch):
    calls = []
    monkeypatch.setenv("APIFY_TOKEN", "x")
    monkeypatch.setattr(apify_budget, "usage", lambda token=None: {"used": 20.9, "limit": 21, "cycle_end": None})
    monkeypatch.setattr(book_odds, "fetch_league", lambda *a, **k: calls.append(a) or [])
    from datetime import datetime, timedelta, timezone
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    events = [{"commence_time": kickoff, "home_team": "A", "away_team": "B"}]
    assert book_odds.daily_refresh("soccer_uefa_nations_league", events) is False
    assert calls == []


def test_the_morning_read_falls_back_to_1x2_near_the_cap(monkeypatch):
    calls = []
    monkeypatch.setenv("APIFY_TOKEN", "x")
    # Full book for one match costs 0.023, 1X2 0.003; 19.98 leaves room for 1X2 only.
    monkeypatch.setattr(apify_budget, "usage", lambda token=None: {"used": 19.98, "limit": 21, "cycle_end": None})
    monkeypatch.setattr(book_odds, "fetch_league",
                        lambda sport, items, full_book: calls.append(full_book) or [{"home_team": "A"}])
    monkeypatch.setattr(book_odds, "store", lambda *a, **k: None)
    from datetime import datetime, timedelta, timezone
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    events = [{"commence_time": kickoff, "home_team": "A", "away_team": "B"}]
    assert book_odds.daily_refresh("soccer_uefa_nations_league", events) is True
    assert calls == [False]


def _soon(minutes):
    from datetime import datetime, timedelta, timezone
    return [{"commence_time": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
             "home_team": "A", "away_team": "B", "sport_key": "soccer_germany_bundesliga"}]


def test_an_empty_morning_read_is_retried_once_then_left(monkeypatch):
    from datetime import timedelta
    calls = []
    monkeypatch.setenv("APIFY_TOKEN", "x")
    monkeypatch.setattr(book_odds, "spend_path", lambda: __import__("pathlib").Path("/nonexistent/spend.json"))
    monkeypatch.setattr(book_odds, "_record_spend", lambda usd: None)
    monkeypatch.setattr(book_odds, "fetch_league", lambda *a, **k: calls.append(1) or [])
    events = _soon(300)
    assert book_odds.daily_refresh("soccer_germany_bundesliga", events) is False
    assert book_odds.morning_retries_due() == []                     # not yet: 30 minutes
    later = book_odds._now() + timedelta(minutes=31)
    assert book_odds.morning_retries_due(later) == ["soccer_germany_bundesliga"]
    assert book_odds.morning_retries_due(later) == []                # handed out once
    book_odds.daily_refresh("soccer_germany_bundesliga", events, retry=True)
    assert "soccer_germany_bundesliga" not in book_odds._morning_retry   # one retry, then stop
    assert len(calls) == 2


def test_a_last_hour_read_is_not_repeated_within_the_cooldown(monkeypatch):
    calls = []
    monkeypatch.setenv("APIFY_TOKEN", "x")
    monkeypatch.setattr(book_odds, "_record_spend", lambda usd: None)
    monkeypatch.setattr(book_odds, "load", lambda: {"fixtures": []})
    monkeypatch.setattr(book_odds, "store", lambda *a, **k: None)
    # The read never brings this match's book (a name that does not match).
    monkeypatch.setattr(book_odds, "fetch_league", lambda *a, **k: calls.append(1) or [])
    events = _soon(40)
    book_odds.refresh_if_due("soccer_germany_bundesliga", events)
    book_odds.refresh_if_due("soccer_germany_bundesliga", events)
    book_odds.refresh_if_due("soccer_germany_bundesliga", events)
    assert len(calls) == 1


def test_a_full_read_without_extra_markets_keeps_1x2_and_is_tried_again(monkeypatch, tmp_path):
    from datetime import timedelta
    calls, stored = [], []
    monkeypatch.setenv("APIFY_TOKEN", "x")
    monkeypatch.setattr(book_odds, "_record_spend", lambda usd: None)
    monkeypatch.setattr(book_odds, "load", lambda: {"fixtures": []})
    monkeypatch.setattr(book_odds, "store", lambda sport, fixtures, replace=False: stored.append(fixtures))
    empty = {"totals": [], "spreads": [], "btts": None}
    monkeypatch.setattr(book_odds, "fetch_league", lambda *a, **k: calls.append(1) or
                        [{"home_team": "A", "away_team": "B", "odds": {"home": 2.0, "draw": 3.4, "away": 3.6},
                          "fetched_at": "x", "markets": empty}])
    events = _soon(40)
    assert book_odds.refresh_if_due("soccer_germany_bundesliga", events) is False
    assert "markets" not in stored[-1][0] and stored[-1][0]["odds"]["home"] == 2.0   # 1X2 kept, book not marked read
    assert book_odds.REFRESH_LOG["soccer_germany_bundesliga"]["outcome"].startswith("failed: no extra markets")
    # After the cooldown the next tick reads again.
    monkeypatch.setattr(book_odds, "_now", lambda: book_odds.datetime.now(book_odds.timezone.utc) + timedelta(minutes=21))
    book_odds.refresh_if_due("soccer_germany_bundesliga", events)
    assert len(calls) == 2


def test_an_empty_book_from_the_scraper_is_not_a_fresh_book(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import src.price_tip as price_tip
    now = datetime.now(timezone.utc)
    event = {"commence_time": (now + timedelta(minutes=40)).isoformat(), "home_team": "A", "away_team": "B"}
    for markets, fresh in (({"totals": [], "spreads": [], "btts": None}, False), ({}, True),
                           ({"totals": [{"point": 2.5, "over": 1.9, "under": 1.9}], "spreads": [], "btts": None}, True)):
        fixture = {"markets": markets, "markets_fetched_at": now.isoformat()}
        monkeypatch.setattr(price_tip, "match_fixture", lambda e, f, events=None, fx=fixture: fx)
        assert book_odds._has_fresh_book([fixture], event) is fresh


def test_an_empty_last_hour_read_is_retried_once_a_day_then_left(monkeypatch):
    from datetime import timedelta
    calls = []
    monkeypatch.setenv("APIFY_TOKEN", "x")
    monkeypatch.setattr(book_odds, "_record_spend", lambda usd: None)
    monkeypatch.setattr(book_odds, "load", lambda: {"fixtures": []})
    monkeypatch.setattr(book_odds, "store", lambda *a, **k: None)
    monkeypatch.setattr(book_odds, "fetch_league", lambda *a, **k: calls.append(1) or
                        [{"home_team": "A", "away_team": "B", "odds": {"home": 2.0, "draw": 3.4, "away": 3.6},
                          "fetched_at": "x", "markets": {"totals": [], "spreads": [], "btts": None}}])
    events = _soon(70)
    base = book_odds.datetime.now(book_odds.timezone.utc)
    for minutes in (0, 21, 42):
        monkeypatch.setattr(book_odds, "_now", lambda m=minutes: base + timedelta(minutes=m))
        book_odds.refresh_if_due("soccer_germany_bundesliga", events)
    assert len(calls) == 2
    assert book_odds.REFRESH_LOG["soccer_germany_bundesliga"]["outcome"].endswith("no retry today")
    lines = book_odds.REFRESH_LOG_PATH.read_text().splitlines()
    assert len(lines) == 2                                     # kept on disk, not only in memory


def test_store_never_replaces_good_markets_with_empty_ones(monkeypatch, tmp_path):
    monkeypatch.setenv("BOOK_ODDS_PATH", str(tmp_path / "book.json"))
    good = {"totals": [{"point": 2.5, "over": 1.9, "under": 1.9}], "spreads": [], "btts": None}
    f = {"sport_key": "s", "home_team": "A", "away_team": "B", "commence_time": "2026-10-13T19:00:00Z",
         "odds": {"home": 2.0, "draw": 3.4, "away": 3.6}}
    book_odds.store("s", [{**f, "fetched_at": "2026-10-13T06:00:00+00:00", "markets": good}])
    book_odds.store("s", [{**f, "fetched_at": "2026-10-13T18:00:00+00:00",
                           "markets": {"totals": [], "spreads": [], "btts": None}}])
    kept = book_odds.load()["fixtures"][0]
    assert kept["markets"] == good and kept["markets_fetched_at"] == "2026-10-13T06:00:00+00:00"
    assert kept["fetched_at"] == "2026-10-13T18:00:00+00:00"   # the newer 1X2 price still wins

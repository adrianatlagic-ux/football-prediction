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


def test_an_empty_morning_read_is_retried_twice_then_left(monkeypatch):
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
    assert book_odds._morning_retry["soccer_germany_bundesliga"]["attempts"] == 2
    book_odds.daily_refresh("soccer_germany_bundesliga", events, retry=True)
    assert "soccer_germany_bundesliga" not in book_odds._morning_retry   # two retries, then stop
    assert len(calls) == 3


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

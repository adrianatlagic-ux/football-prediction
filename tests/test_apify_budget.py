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
    monkeypatch.setattr(book_odds, "fetch_league", lambda sport, items, full_book: calls.append(full_book) or [])
    monkeypatch.setattr(book_odds, "store", lambda *a, **k: None)
    from datetime import datetime, timedelta, timezone
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    events = [{"commence_time": kickoff, "home_team": "A", "away_team": "B"}]
    assert book_odds.daily_refresh("soccer_uefa_nations_league", events) is True
    assert calls == [False]

"""A restart on the same day must not spend Odds API credits again."""
from api import app as api


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "ODDS_SNAPSHOT_PATH", tmp_path / "odds_snapshot.json")
    monkeypatch.setattr(api, "_odds_cache", [])
    monkeypatch.setattr(api, "_odds_daily_refresh_date", None)
    monkeypatch.setattr(api, "_refresh_book_daily", lambda events: None)


def test_restart_reuses_todays_snapshot(tmp_path, monkeypatch):
    calls = []
    event = {"id": "x", "sport_key": "soccer_germany_bundesliga", "home_team": "A", "away_team": "B",
             "commence_time": "2099-01-01T00:00:00Z", "bookmakers": []}
    monkeypatch.setattr(api, "_fetch_odds", lambda: calls.append(1) or [event])
    _reset(monkeypatch, tmp_path)
    api._get_odds()
    assert calls == [1] and (tmp_path / "odds_snapshot.json").exists()
    _reset(monkeypatch, tmp_path)          # a new process, same day
    api._get_odds()
    assert calls == [1]


def test_final_prices_survive_restart_without_paid_read(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    event = {'id': 'x', 'sport_key': 'soccer_germany_bundesliga', 'home_team': 'A', 'away_team': 'B',
             'commence_time': (now + timedelta(minutes=30)).isoformat(), 'bookmakers': []}
    final = {**event, 'bookmakers': [{'key': 'test', 'markets': [{'key': 'h2h', 'outcomes': [{'name': 'A', 'price': 2}]}]}]}
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(api, '_final_odds_cache', {})
    monkeypatch.setattr(api, '_final_odds_attempts', {})
    monkeypatch.setattr(api, '_odds_cache_fetched_at', 0)
    monkeypatch.setattr(api, 'ODDS_CACHE_TTL_SECONDS', 0)
    monkeypatch.setattr(api, '_retry_book_morning', lambda events: None)
    monkeypatch.setattr(api, '_fetch_odds', lambda: [event])
    calls = []
    monkeypatch.setattr(api, '_fetch_league_odds', lambda *args: calls.append(1) or [final])
    first = api._get_odds()
    assert first[0]['odds_stage'] == 'final'
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(api, '_final_odds_cache', {})
    monkeypatch.setattr(api, '_final_odds_attempts', {})
    monkeypatch.setattr(api, '_fetch_odds', lambda: (_ for _ in ()).throw(AssertionError('morning read repeated')))
    assert api._get_odds() == first
    assert len(calls) == 1


def test_failed_final_cooldown_survives_restart(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    event = {'id': 'retry', 'sport_key': 'soccer_germany_bundesliga', 'home_team': 'A', 'away_team': 'B',
             'commence_time': (now + timedelta(minutes=30)).isoformat(), 'bookmakers': []}
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(api, '_final_odds_cache', {})
    monkeypatch.setattr(api, '_final_odds_attempts', {})
    monkeypatch.setattr(api, 'ODDS_CACHE_TTL_SECONDS', 0)
    monkeypatch.setattr(api, '_retry_book_morning', lambda events: None)
    monkeypatch.setattr(api, '_fetch_odds', lambda: [event])
    calls = []
    def fail(*args):
        calls.append(1)
        raise OSError('unavailable')
    monkeypatch.setattr(api, '_fetch_league_odds', fail)
    assert api._get_odds()[0]['final_refresh_status'] == 'pending_or_failed'
    _reset(monkeypatch, tmp_path)
    monkeypatch.setattr(api, '_final_odds_cache', {})
    monkeypatch.setattr(api, '_final_odds_attempts', {})
    assert api._get_odds()[0]['final_refresh_status'] == 'pending_or_failed'
    assert calls == [1]

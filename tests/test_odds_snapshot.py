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

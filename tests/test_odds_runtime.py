from datetime import datetime, timedelta, timezone
import json
from api import app as api
from src.odds_runtime import read, write


def test_quota_observations_survive_restart_and_keep_last_paid_read(monkeypatch):
    api._note_odds_quota({'x-requests-remaining': '401', 'x-requests-used': '99', 'x-requests-last': '3'})
    status = api._odds_status()
    assert status['quota']['remaining_credits'] == 401
    assert status['quota']['last_paid_request']['credits'] == 3
    assert status['quota']['observed_at']
    api._note_odds_quota({'x-requests-remaining': '401', 'x-requests-used': '99', 'x-requests-last': '0'})
    assert api._odds_status()['quota']['last_request_credits'] == 0
    assert api._odds_status()['quota']['last_paid_request']['credits'] == 3
    previous = api._odds_status()['quota']
    api._note_odds_quota(None)
    assert api._odds_status()['quota'] == previous
    # Only safe numeric quota headers, never URLs, credentials or other headers.
    assert 'authorization' not in json.dumps(previous).lower()


def test_refresh_status_reports_earliest_final_window_without_fetch(monkeypatch):
    now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(api, 'datetime', Clock)
    monkeypatch.setattr(api, '_odds_daily_refresh_date', now.date().isoformat())
    event = {'id': 'x', 'sport_key': 'soccer_germany_bundesliga', 'home_team': 'A', 'away_team': 'B',
             'commence_time': (now + timedelta(hours=3)).isoformat()}
    monkeypatch.setattr(api, '_odds_cache', [event])
    monkeypatch.setattr(api, '_final_odds_cache', {})
    monkeypatch.setattr(api, '_final_odds_attempts', {})
    assert api._odds_status()['next_refresh_due_at'] == (now + timedelta(hours=2)).isoformat()
    key = (event['sport_key'], event['id'], event['commence_time'])
    monkeypatch.setattr(api, '_final_odds_cache', {key: event})
    assert api._odds_status()['next_refresh_due_at'] == '2026-10-21T06:00:00+00:00'


def test_restore_refuses_expired_or_wrong_identity_and_corrupt_file(monkeypatch):
    now = datetime.now(timezone.utc)
    event = {'id': 'x', 'sport_key': 'soccer_germany_bundesliga', 'home_team': 'A', 'away_team': 'B',
             'commence_time': (now + timedelta(minutes=30)).isoformat(),
             'odds_stage': 'final', 'odds_fetched_at': now.isoformat()}
    monkeypatch.setattr(api, '_odds_cache', [event])
    monkeypatch.setattr(api, '_final_odds_cache', {})
    monkeypatch.setattr(api, '_final_odds_attempts', {})
    path = api._odds_runtime_path('final')
    write(path, {'events': [{**event, 'home_team': 'Changed'}]})
    api._restore_final_odds(now)
    assert not api._final_odds_cache
    write(path, {'events': [event]})
    api._restore_final_odds(now + timedelta(hours=1))
    assert not api._final_odds_cache
    path.write_text('{broken')
    api._restore_final_odds(now)
    assert not api._final_odds_cache
    assert read(path) == {}


def test_status_tolerates_invalid_persistent_schema():
    write(api._odds_runtime_path('final'), {'events': None, 'attempts': 'bad'})
    assert api._odds_status()['quota']['remaining_credits'] is None
    write(api._odds_runtime_path('final'), {'events': [None, 'bad'], 'attempts': [None]})
    assert api._odds_status()['next_refresh_due_at']


def test_status_honors_saved_retry_cooldown(monkeypatch):
    now = datetime(2026, 10, 20, 16, 15, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(api, 'datetime', Clock)
    monkeypatch.setattr(api, '_odds_daily_refresh_date', now.date().isoformat())
    event = {'id': 'retry', 'sport_key': 'soccer_germany_bundesliga',
             'commence_time': '2026-10-20T17:00:00+00:00'}
    monkeypatch.setattr(api, '_odds_cache', [event])
    monkeypatch.setattr(api, '_final_odds_cache', {})
    monkeypatch.setattr(api, '_final_odds_attempts', {})
    write(api._odds_runtime_path('final'), {'attempts': [{'key': [event['sport_key'], event['id'], event['commence_time']], 'at': now.timestamp()}]})
    assert api._odds_status()['next_refresh_due_at'] == '2026-10-20T16:30:00+00:00'

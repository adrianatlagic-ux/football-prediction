from copy import deepcopy
from datetime import datetime, timedelta, timezone

from api import app as api
from src.ai_tip_research import fresh_candidates
from src.odds_schedule import retain_missing_quotes, stamp_event
from tests.test_bet_selection import event, prediction


def test_missing_bet_stays_available_and_new_quote_replaces_it():
    now = datetime.now(timezone.utc)
    old = event()
    old['commence_time'] = (now + timedelta(minutes=30)).isoformat()
    old['bookmakers'][0]['key'] = 'old-book'
    old['bookmakers'][0]['last_update'] = (now - timedelta(hours=8)).isoformat()
    old['bookmakers'][0]['markets'].append({'key': 'totals', 'outcomes': [
        {'name': 'Over', 'point': 2.5, 'price': 1.8},
        {'name': 'Under', 'point': 2.5, 'price': 1.9}]})
    old = stamp_event(old, now - timedelta(hours=8), 'daily')
    new = deepcopy(old)
    new['bookmakers'] = [{'key': 'new-book', 'title': 'New', 'last_update': now.isoformat(),
                          'markets': [deepcopy(old['bookmakers'][0]['markets'][0])]}]
    merged = stamp_event(retain_missing_quotes(old, new), now, 'final')
    vb = api._compute_value_bets(prediction(), [merged], 'A', 'B')
    retained = next(b for b in vb['bets'] if b['market'] == 'Over/Under 2.5' and b['outcome'] == 'Over')
    assert retained['best_odds'] == 1.8
    assert retained['quote_carried_forward'] and not retained['quote_fresh']
    assert retained['quote_last_update'] == old['bookmakers'][0]['last_update']
    assert retained['market_probability'] is not None
    assert retained in fresh_candidates(vb)

    new['bookmakers'][0]['markets'].append({'key': 'totals', 'outcomes': [
        {'name': 'Over', 'point': 2.5, 'price': 1.65}]})
    updated = stamp_event(retain_missing_quotes(old, new), now, 'final')
    offer = api._best_price(updated, 'totals', 'Over', point=2.5)
    assert offer['price'] == 1.65 and not offer['carried_forward']
    assert api._best_price(updated, 'totals', 'Under', point=2.5)['carried_forward']


def test_retention_does_not_mix_distinct_matches():
    now = datetime.now(timezone.utc)
    old = stamp_event(event(), now, 'daily')
    new = {**old, 'id': 'another-match', 'bookmakers': []}
    assert retain_missing_quotes(old, new)['bookmakers'] == []


def test_daily_refresh_preserves_missing_quote_across_restart(tmp_path, monkeypatch):
    import json
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=1)
    old = event()
    old['commence_time'] = (now + timedelta(hours=3)).isoformat()
    old['bookmakers'][0]['key'] = 'old-book'
    old['bookmakers'][0]['last_update'] = old_time.isoformat()
    old['bookmakers'][0]['markets'].append({'key': 'totals', 'outcomes': [
        {'name': 'Over', 'point': 2.5, 'price': 1.8}]})
    current = deepcopy(old)
    current['bookmakers'][0]['last_update'] = now.isoformat()
    current['bookmakers'][0]['markets'].pop()
    path = tmp_path / 'odds_snapshot.json'
    path.write_text(json.dumps({'events': [old], 'fetched_at': old_time.isoformat(), 'stage': 'daily'}))
    for key, value in [('ODDS_SNAPSHOT_PATH', path), ('_odds_cache', []), ('_odds_daily_refresh_date', None),
                       ('_odds_cache_fetched_at', 0), ('ODDS_CACHE_TTL_SECONDS', 0),
                       ('_final_odds_cache', {}), ('_final_odds_attempts', {})]:
        monkeypatch.setattr(api, key, value)
    monkeypatch.setattr(api, '_fetch_odds', lambda: [deepcopy(current)])
    monkeypatch.setattr(api, '_refresh_book_daily', lambda events: None)
    monkeypatch.setattr(api, '_retry_book_morning', lambda events: None)
    first = api._get_odds()[0]
    assert api._best_price(first, 'totals', 'Over', 2.5)['carried_forward']
    monkeypatch.setattr(api, '_odds_cache', [])
    monkeypatch.setattr(api, '_odds_daily_refresh_date', None)
    monkeypatch.setattr(api, '_fetch_odds', lambda: (_ for _ in ()).throw(AssertionError('unexpected fetch')))
    assert api._best_price(api._get_odds()[0], 'totals', 'Over', 2.5)['carried_forward']

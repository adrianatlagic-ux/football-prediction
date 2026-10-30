import pytest

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from api import app as api
from src.bet_selection import market_consensus
from src.ai_tip_research import fresh_candidates
from src.odds_schedule import retain_missing_quotes, stamp_event
from tests.test_bet_selection import event, prediction


@pytest.mark.parametrize("new_book", ["new-book", "old-book"])
def test_missing_bet_stays_available_and_new_quote_replaces_it(new_book):
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
    new['bookmakers'] = [{'key': new_book, 'title': 'New', 'last_update': now.isoformat(),
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
    expected = (1 / 1.8) / (1 / 1.8 + 1 / 1.9)
    assert market_consensus(updated, 'totals', 'Over', 2.5, now) == expected
    assert market_consensus(updated, 'totals', 'Under', 2.5, now) == (1 / 1.9) / (1 / 1.8 + 1 / 1.9)
    bets = api._compute_value_bets(prediction(), [updated], 'A', 'B')
    over = next(b for b in bets['bets'] if b['market'] == 'Over/Under 2.5' and b['outcome'] == 'Over')
    assert over['best_odds'] == 1.65 and over['market_probability'] == round(expected, 4)
    assert over in fresh_candidates(bets)
    # A subsequent partial refresh keeps the original evidence and timestamps.
    again = stamp_event(retain_missing_quotes(updated, new), now, 'final')
    assert market_consensus(again, 'totals', 'Over', 2.5, now) == expected
    assert api._best_price(again, 'totals', 'Under', 2.5)['last_update'] == old['bookmakers'][0]['last_update']
    # Once a complete current market exists it takes precedence over history.
    complete = deepcopy(new)
    complete['bookmakers'][0]['markets'][-1]['outcomes'].append(
        {'name': 'Under', 'point': 2.5, 'price': 2.1})
    replaced = stamp_event(retain_missing_quotes(updated, complete), now, 'final')
    assert market_consensus(replaced, 'totals', 'Over', 2.5, now) == (1 / 1.65) / (1 / 1.65 + 1 / 2.1)



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


def test_split_book_replacements_keep_historical_evidence_without_old_offers():
    now = datetime.now(timezone.utc)
    old = event()
    old['commence_time'] = (now + timedelta(minutes=30)).isoformat()
    old['bookmakers'] = [{'key': 'original', 'last_update': now.isoformat(), 'markets': [
        {'key': 'totals', 'outcomes': [{'name': 'Over', 'point': 2.5, 'price': 1.8},
                                     {'name': 'Under', 'point': 2.5, 'price': 1.9}]}]}]
    old = stamp_event(old, now, 'final')
    new = deepcopy(old)
    new['bookmakers'] = [
        {'key': side, 'last_update': now.isoformat(), 'markets': [
            {'key': 'totals', 'outcomes': [{'name': side, 'point': 2.5, 'price': price}]}]}
        for side, price in [('Over', 1.7), ('Under', 2.0)]]
    expected = (1 / 1.8) / (1 / 1.8 + 1 / 1.9)
    merged = stamp_event(retain_missing_quotes(old, new), now, 'final')
    for _ in range(3):
        assert market_consensus(merged, 'totals', 'Over', 2.5, now) == expected
        assert api._best_price(merged, 'totals', 'Over', 2.5)['price'] == 1.7
        assert api._best_price(merged, 'totals', 'Under', 2.5)['price'] == 2.0
        # Evidence survives both a fresh response and injection-style pass-through.
        merged = stamp_event(retain_missing_quotes(merged, new), now, 'final')
        merged = retain_missing_quotes(merged, merged)
    evidence_book = next(b for b in merged['bookmakers'] if b['key'] == 'original')
    assert len(evidence_book['markets']) == 1
    assert evidence_book['markets'][0]['outcomes'] == []
    complete = deepcopy(new)
    complete['bookmakers'][0]['markets'][0]['outcomes'].append(
        {'name': 'Under', 'point': 2.5, 'price': 2.1})
    updated = stamp_event(retain_missing_quotes(merged, complete), now, 'final')
    assert market_consensus(updated, 'totals', 'Over', 2.5, now) == (1 / 1.7) / (1 / 1.7 + 1 / 2.1)

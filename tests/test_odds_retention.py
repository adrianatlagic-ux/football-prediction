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


@pytest.mark.parametrize('key,names,points', [
    ('h2h', ['A', 'Draw', 'B'], [None, None, None]),
    ('totals', ['Over', 'Under'], [2.5, 2.5]),
    ('spreads', ['A', 'B'], [0.5, -0.5]),
    ('btts', ['Yes', 'No'], [None, None]),
])
@pytest.mark.parametrize('reverse_history', [False, True])
def test_latest_complete_market_survives_successive_fetches_and_restart(key, names, points, reverse_history):
    import json
    now = datetime.now(timezone.utc)
    base = event()
    base['commence_time'] = (now + timedelta(hours=1)).isoformat()

    def snapshot(prices, fetched):
        outcomes = [dict(name=name, price=price, **({'point': point} if point is not None else {}))
                    for name, point, price in zip(names, points, prices)]
        return stamp_event({**base, 'bookmakers': [
            {'key': 'book', 'last_update': fetched.isoformat(),
             'markets': [{'key': key, 'outcomes': outcomes}]}]}, fetched, 'final')

    old_prices = [1.8, 2.0] if len(names) == 2 else [1.8, 4.0, 5.0]
    latest_prices = [1.4, 3.0] if len(names) == 2 else [1.4, 5.0, 7.0]
    old = snapshot(old_prices, now - timedelta(hours=6))
    current = snapshot(latest_prices, now - timedelta(hours=2))
    merged = retain_missing_quotes(old, current)
    # Include old-format caches with several evidence versions in either order.
    legacy = deepcopy(old['bookmakers'][0]['markets'][0])
    legacy.update(last_update=old['bookmakers'][0]['last_update'], carried_forward=True,
                  historical_outcomes=legacy['outcomes'], outcomes=[])
    merged['bookmakers'][0]['markets'].append(legacy)
    if reverse_history:
        merged['bookmakers'][0]['markets'].reverse()
    # A saved cache from the earlier implementation must also give the latest
    # probability before any provider refresh has compacted its history.
    cached = deepcopy(merged)
    for market in cached['bookmakers'][0]['markets']:
        market['carried_forward'] = True
    expected = (1 / latest_prices[0]) / sum(1 / p for p in latest_prices)
    assert market_consensus(cached, key, names[0], points[0], now) == pytest.approx(expected)
    missing = stamp_event({**base, 'bookmakers': []}, now, 'final')
    for _ in range(5):
        merged = stamp_event(retain_missing_quotes(merged, missing), now, 'final')
        # Round-trip as the on-disk snapshot does before a process restart.
        merged = json.loads(json.dumps(merged))
        for name, point, price in zip(names, points, latest_prices):
            offer = api._best_price(merged, key, name, point)
            assert offer['price'] == price
            assert offer['last_update'] == current['bookmakers'][0]['last_update']
            expected = (1 / price) / sum(1 / p for p in latest_prices)
            assert market_consensus(merged, key, name, point, now) == pytest.approx(expected)
        # No growth across repeated absent markets and repeated injection.
        stable = deepcopy(merged)
        merged = retain_missing_quotes(merged, merged)
        assert merged == stable


def test_each_total_line_keeps_its_own_latest_complete_probability():
    now = datetime.now(timezone.utc)
    base = event()
    base['commence_time'] = (now + timedelta(hours=1)).isoformat()

    def snapshot(lines, fetched):
        return stamp_event({**base, 'bookmakers': [{'key': 'book', 'last_update': fetched.isoformat(),
            'markets': [{'key': 'totals', 'outcomes': [
                {'name': name, 'point': line, 'price': price}
                for line, over, under in lines for name, price in [('Over', over), ('Under', under)]]}]}]},
            fetched, 'final')

    old = snapshot([(2.5, 1.8, 2.0), (3.5, 2.5, 1.6)], now - timedelta(hours=6))
    fresh = snapshot([(2.5, 1.4, 3.0)], now - timedelta(hours=2))
    merged = retain_missing_quotes(old, fresh)
    missing = stamp_event({**base, 'bookmakers': []}, now, 'final')
    merged = stamp_event(retain_missing_quotes(merged, missing), now, 'final')
    assert api._best_price(merged, 'totals', 'Over', 2.5)['price'] == 1.4
    assert api._best_price(merged, 'totals', 'Over', 3.5)['price'] == 2.5
    assert market_consensus(merged, 'totals', 'Over', 2.5, now) == pytest.approx((1 / 1.4) / (1 / 1.4 + 1 / 3.0))
    assert market_consensus(merged, 'totals', 'Over', 3.5, now) == pytest.approx((1 / 2.5) / (1 / 2.5 + 1 / 1.6))


def test_many_refreshes_follow_replace_or_keep_rule_for_every_selection():
    import json
    import random
    rng = random.Random(37)
    now = datetime.now(timezone.utc)
    base = event()
    base['commence_time'] = (now + timedelta(hours=2)).isoformat()
    selections = [('h2h', name, None) for name in ['A', 'Draw', 'B']]
    selections += [('totals', name, line) for line in [1.5, 2.5, 3.5] for name in ['Over', 'Under']]
    selections += [('spreads', 'A', 0.5), ('spreads', 'B', -0.5)]
    selections += [('btts', name, None) for name in ['Yes', 'No']]
    expected = {}
    merged = None
    for step in range(30):
        fetched = now - timedelta(minutes=10 * (29 - step))
        books = []
        replacements = {}
        for book_key in ['first', 'second']:
            markets = {}
            for key, name, point in selections:
                if step and rng.random() < 0.6:
                    continue
                price = round(rng.uniform(1.2, 4.0), 2)
                outcome = {'name': name, 'price': price}
                if point is not None:
                    outcome['point'] = point
                markets.setdefault(key, []).append(outcome)
                identity = (key, name, point)
                replacements[identity] = max(replacements.get(identity, 0), price)
            books.append({'key': book_key, 'last_update': fetched.isoformat(),
                          'markets': [{'key': key, 'outcomes': outcomes} for key, outcomes in markets.items()]})
        current = stamp_event({**base, 'bookmakers': books}, fetched, 'final')
        merged = retain_missing_quotes(merged, current) if merged else current
        expected.update(replacements)
        # Include restart and repeated injection paths after every response.
        merged = json.loads(json.dumps(merged))
        merged = retain_missing_quotes(merged, merged)
        for (key, name, point), price in expected.items():
            assert api._best_price(merged, key, name, point)['price'] == price


@pytest.mark.parametrize('reverse_offers', [False, True])
def test_quote_map_uses_newest_offer_and_does_not_erase_missing_or_invalid_quotes(reverse_offers):
    now = datetime.now(timezone.utc)
    base = event()
    base['commence_time'] = (now + timedelta(hours=1)).isoformat()
    old_time = now - timedelta(hours=3)
    old = stamp_event({**base, 'bookmakers': [{'key': 'same-book', 'last_update': old_time.isoformat(),
        'markets': [{'key': 'totals', 'outcomes': [
            {'name': 'Over', 'point': 2.5, 'price': 1.8},
            {'name': 'Under', 'point': 2.5, 'price': 1.9},
            {'name': 'Over', 'point': 3.5, 'price': 2.2}]}]}]}, old_time, 'daily')
    refreshed = [
        {'key': 'totals', 'last_update': (now - timedelta(minutes=5)).isoformat(),
         'outcomes': [{'name': 'Over', 'point': 2.5, 'price': 1.7}]},
        {'key': 'totals', 'last_update': now.isoformat(),
         'outcomes': [{'name': 'Over', 'point': 2.5, 'price': 1.4},
                      {'name': 'Under', 'point': 2.5, 'price': None},
                      {'name': 'Over', 'point': 3.5, 'price': float('nan')}]}]
    if reverse_offers:
        refreshed.reverse()
    new = stamp_event({**base, 'bookmakers': [
        {'key': 'same-book', 'last_update': now.isoformat(), 'markets': refreshed},
        {'key': 'other-book', 'last_update': now.isoformat(), 'markets': [
            {'key': 'totals', 'outcomes': [{'name': 'Over', 'point': 2.5, 'price': 1.5}]}]}]}, now, 'final')
    original_old, original_new = deepcopy(old), deepcopy(new)
    merged = retain_missing_quotes(old, new)
    offers = {o['bookmaker_key']: o['price'] for o in api._available_prices(merged, 'totals', 'Over', 2.5)}
    assert offers == {'same-book': 1.4, 'other-book': 1.5}
    assert api._best_price(merged, 'totals', 'Over', 2.5)['price'] == 1.5
    assert api._best_price(merged, 'totals', 'Under', 2.5)['price'] == 1.9
    assert api._best_price(merged, 'totals', 'Over', 3.5)['price'] == 2.2
    assert old == original_old and new == original_new

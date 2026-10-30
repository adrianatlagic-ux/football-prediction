import pytest
from api import app as api


def bet(market='Over/Under 2.5', outcome='Under', team=None, model=.49, market_p=.53, odds=1.8):
    return {'market': market, 'outcome': outcome, 'team': team,
            'model_probability_raw': model, 'market_probability': market_p,
            'best_odds': odds, 'quote_fresh': True}


def decide(pick, bets, **agent):
    return api._bet_tip({'home_team': 'A', 'away_team': 'B', 'bets': bets},
                        {'pick': pick, 'revised_from_previous': False, **agent})


@pytest.mark.parametrize('pick,alternative', [
    (bet(), bet('Over/Under 3.5', model=.72, market_p=.70, odds=1.30)),
    (bet(outcome='Over'), bet('Over/Under 1.5', 'Over', model=.75, market_p=.70)),
    (bet('1X2', 'home_win', 'A'), bet('Handicap +0.5', 'handicap', 'A', model=.75, market_p=.70)),
    (bet('1X2', 'away_win', 'B'), bet('Handicap +0.5', 'handicap', 'B', model=.75, market_p=.70)),
    (bet('Handicap -1.5', 'handicap', 'A'), bet('Handicap -0.5', 'handicap', 'A', model=.75, market_p=.70)),
])
def test_weaker_bet_is_accepted_without_edge_requirement(pick, alternative):
    out = decide(pick, [alternative])
    assert out['tip'] == alternative and out['is_fallback']
    assert out['original_pick'] == pick and out['confirmed']
    assert out['rule'] == 'ki_model_fallback_v3'


def test_original_remains_first_choice_and_ai_change_still_blocks():
    pick, alternative = bet(model=.54), bet('Over/Under 3.5', model=.75, market_p=.70)
    assert decide(pick, [alternative])['tip'] == pick
    assert decide(pick, [alternative], revised_from_previous=True)['status'] == 'ai_unsure'
    pick['model_probability_raw'] = .49
    assert decide(pick, [alternative], revised_from_previous=True)['tip'] is None
    assert not decide(pick, [alternative], revised_from_previous=None)['confirmed']


@pytest.mark.parametrize('alternative', [
    bet('Over/Under 1.5', model=.75, market_p=.70),  # harder under
    bet('Over/Under 3.5', 'Over', model=.75, market_p=.70),  # opposite side
    bet('Over/Under 3.5', model=.69, market_p=.70),
    bet('Over/Under 3.5', model=.75, market_p=.70, odds=1.29),
    {**bet('Over/Under 3.5', model=.75, market_p=.70), 'quote_fresh': False},
    {**bet('Over/Under 3.5', model=.75, market_p=.70), 'market_probability': None},
])
def test_no_fallback_without_all_conditions(alternative):
    assert decide(bet(), [alternative])['status'] == 'no_agreement'


def test_nearest_qualifying_line_and_equal_model_market_are_accepted():
    near = bet('Over/Under 3.5', model=.70, market_p=.70)
    far = bet('Over/Under 4.5', model=.90, market_p=.80)
    assert decide(bet(), [far, near])['tip'] == near
    assert decide(bet(odds=1.2), [near])['tip'] is None
    assert decide({**bet(), 'market_probability': None}, [near])['tip'] is None


def test_logging_keeps_complete_candidates_and_fallback_origin():
    from scripts.log_bets import _build_entry
    pick = bet()
    alternative = bet('Over/Under 3.5', model=.72, market_p=.70)
    result = decide(pick, [alternative])
    entry = _build_entry({'home_team': 'A', 'away_team': 'B', 'bets': [pick, alternative],
                          'bet_tip': result}, '2026-10-20T18:30:00Z')
    assert entry['bets'] == [pick, alternative]
    assert entry['bet_tip']['original_pick'] == pick
    assert entry['bet_tip']['tip'] == alternative


@pytest.mark.parametrize('snapshot', [
    {'snapshot_valid': False},
    {'snapshot_valid_until': '2020-01-01T00:00:00Z'},
    {'snapshot_valid_until': 'invalid'},
    {'in_play': True},
])
def test_expired_snapshot_never_keeps_a_cached_tip(snapshot):
    pick = bet(model=.8)
    out = api._bet_tip({'home_team': 'A', 'away_team': 'B', **snapshot}, {'pick': pick})
    assert out['tip'] is None and out['status'] == 'odds_expired'


def test_explicitly_stale_original_cannot_be_promoted():
    assert decide({**bet(model=.8), 'quote_fresh': False}, [])['status'] == 'odds_expired'


def test_retained_original_can_be_used_when_model_agrees():
    pick = {**bet(model=.8), 'quote_fresh': False, 'quote_carried_forward': True}
    assert decide(pick, [])['tip'] == pick

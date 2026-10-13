from copy import deepcopy
import numpy as np
import pytest
from scripts.train_hit_selector import (exclusion, feature_row, context_before_matches,
    verify_offer, flatten, choose, paired_difference, MARKET_FEATURES, MODEL_FEATURES, FORM_FEATURES)


def bet(**changes):
    return dict({'market': '1X2', 'outcome': 'home_win', 'team': 'A', 'probability': .6,
        'market_probability': .55, 'best_odds': 1.7, 'push_probability': 0,
        'suspicious': False}, **changes)


def row():
    return {'date': '2023-01-01', 'season': '2022-23', 'home': 'A', 'away': 'B',
        'home_goals': 2, 'away_goals': 1,
        'candidates': [bet(), bet(outcome='draw', team=None, probability=.2),
                       bet(outcome='away_win', team='B', probability=.2)]}


@pytest.mark.parametrize('changes', [{'suspicious': True}, {'high_deviation': True},
    {'contradicts_favorite': True}, {'best_odds': 1.29}, {'best_odds': 3.01},
    {'market': 'Handicap 0.0'}, {'market': 'Handicap +0.25'}, {'market': 'Over/Under 3.0'},
    {'market_probability': None}, {'probability': float('nan')}])
def test_exclusions_precede_learning(changes):
    assert exclusion(bet(**changes))


def test_negative_ev_is_allowed_for_hit_objective():
    assert exclusion(bet(expected_value=-.1, kelly_stake_pct=0)) is None
    assert exclusion(bet(market='Handicap +1.5', outcome='handicap')) is None


def test_features_do_not_read_outcome_profit_or_closing_prices():
    r = row(); b = bet()
    before = feature_row(b, r, [0]*8, True)
    r.update(home_goals=0, away_goals=9, closing_odds=4.0)
    b.update(profit=100, settlement='loss')
    assert feature_row(b, r, [0]*8, True) == before
    assert len(before) == len(MARKET_FEATURES + MODEL_FEATURES + FORM_FEATURES)


def test_form_excludes_same_day_and_future():
    history = [dict(date=d, home_team='A', away_team='B', home_goals=h, away_goals=a)
               for d, h, a in [('2022-12-01', 2, 1), ('2023-01-01', 9, 0), ('2024-01-01', 0, 9)]]
    contexts = context_before_matches([row()], history)
    assert contexts[('2023-01-01', 'A', 'B')] == [1, 3, 2, 1, 1, 0, 1, 2]


def test_offer_must_be_exact_preclosing_contract():
    verify_offer(bet(), {'B365H': '1.7'}, 'A')
    with pytest.raises(ValueError):
        verify_offer(bet(), {'B365H': '1.8', 'B365CH': '1.7'}, 'A')
    with pytest.raises(ValueError):
        verify_offer(bet(market='Handicap +1.5'), {'AHh': '.5', 'B365AHH': '1.7'}, 'A')


def test_no_duplicate_match_weight_and_selection_is_top_one():
    m = {**row(), 'bets': [{'bet': bet(), 'x': [.55], 'won': 1, 'profit': .7},
                          {'bet': bet(market_probability=.65, probability=.7), 'x': [.65], 'won': 0, 'profit': -1}]}
    X, y, w = flatten([m], 'x')
    assert sum(w) == 1
    picks = choose([m])
    assert len(picks) == 1 and picks[0]['won'] == 0  # picks by probability, not known outcome
    newer = deepcopy(m)
    for b in newer['bets']:
        b['won'] = 1 - b['won']
    assert choose([newer])[0]['bet'] == picks[0]['bet']


def test_bootstrap_is_paired_and_identity_guarded():
    p = {**row(), 'won': 1, 'bet': bet()}
    assert paired_difference([p], [p])['paired_date_bootstrap_95pct'] == [0, 0]
    with pytest.raises(ValueError):
        paired_difference([p], [{**p, 'date': '2024-01-01'}])

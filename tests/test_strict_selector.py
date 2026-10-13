"""Research safeguards: eligibility, chronology, exact contracts and push EV."""
from copy import deepcopy
import numpy as np
import pytest
from scripts.strict_bet_selector import (legal, closing_quote, choose, flatten,
    train, features, ridge_fit, predict)
from src.bet_selection import price_bet


def bet(**kw):
    b = dict(market='1X2', outcome='home_win', team='H', best_odds=2., probability=.6,
             expected_value=.2, kelly_stake_pct=5., suspicious=False, market_probability=.5,
             push_probability=0., x=[.1], profit=1., clv=.1)
    b.update(kw)
    return b


@pytest.mark.parametrize('change', [dict(suspicious=True), dict(expected_value=-.01),
                                    dict(expected_value=.251), dict(kelly_stake_pct=.99)])
def test_ineligible_candidates_not_admitted(change):
    assert not legal(bet(**change))


def test_same_line_required_for_both_handicap_sides():
    q = {'AHCh': '-.75', 'B365CAHH': '1.9', 'B365CAHA': '2.0'}
    assert closing_quote(q, bet(market='Handicap -0.75'), 'H', 'bet365') == (1.9, None)
    assert closing_quote(q, bet(market='Handicap +0.75', team='A'), 'H', 'bet365') == (2., None)
    assert closing_quote(q, bet(market='Handicap -0.5'), 'H', 'bet365') == (None, 'handicap_line_changed')


def test_total_closing_and_missing_not_replaced_by_opening():
    q = {'B365C>2.5': '2.1', 'B365<2.5': '1.8'}
    assert closing_quote(q, bet(market='Over/Under 2.5', outcome='Over'), 'H', 'bet365') == (2.1, None)
    assert closing_quote(q, bet(market='Over/Under 3.5', outcome='Over'), 'H', 'bet365')[0] is None
    assert closing_quote(q, bet(market='Over/Under 2.5', outcome='Under'), 'H', 'bet365')[0] is None


def test_closing_missing_does_not_change_selection_or_profit_training_pool():
    a, b = bet(), bet(outcome='away_win', team='A', kelly_stake_pct=2.)
    m = {'eligible': [a, b]}
    models = {'profit': {'model': {'constant': .1}}}
    assert choose(m, models)['profit_rank'] is a
    a['clv'] = None
    assert choose(m, models)['profit_rank'] is a
    assert len(flatten([m], 'profit')[1]) == 2
    assert len(flatten([m], 'clv')[1]) == 1


def test_no_bet_is_not_zero_roi_claim_and_constant_ties_use_kelly():
    m = {'eligible': [bet(kelly_stake_pct=2), bet(kelly_stake_pct=4)]}
    picks = choose(m, {'profit': {'model': {'constant': -.01}}})
    assert picks['profit_positive'] is None
    assert picks['profit_rank'] is picks['kelly']


def test_feature_ev_handles_draw_no_bet_refund():
    pred = dict(home_team='H', away_team='A', probability_home_win=.4,
                probability_draw=.3, probability_away_win=.3)
    b = bet(market='Handicap 0.0')
    b.update(price_bet(b, pred, None))
    hda = [bet(), bet(outcome='away_win', team='A', probability=.3)]
    x = features(b, hda, [pred, pred, pred], price_bet)
    assert x[2] == pytest.approx(.1)
    assert x[2] != pytest.approx(b['probability']*b['best_odds']-1)


def test_temporal_cv_never_splits_same_date_or_fixture(monkeypatch):
    import scripts.strict_bet_selector as mod
    matches=[]
    for i, date in enumerate(['2021-10-01','2022-02-01','2022-09-01','2023-02-01']):
        matches.append({'date':date, 'eligible':[bet(x=[i],profit=.1),bet(x=[i],profit=-.1)]})
    original=mod.ridge_fit
    train_max=[]
    def wrapped_fit(X,y,w,alpha):
        train_max.append(float(np.max(np.asarray(X))))
        return original(X,y,w,alpha)
    original_predict=mod.predict
    def wrapped_predict(model,X):
        assert float(np.min(X)) > train_max[-1]
        return original_predict(model,X)
    monkeypatch.setattr(mod,'ridge_fit',wrapped_fit)
    monkeypatch.setattr(mod,'predict',wrapped_predict)
    result=train(matches,'profit')
    assert result['selected_alpha'] is None


def test_match_weighting_is_equal_despite_candidate_count():
    _,_,w = flatten([{'eligible':[bet()]},{'eligible':[bet(),bet(),bet()]}],'profit')
    assert w[0] == 1 and sum(w[1:]) == pytest.approx(1)

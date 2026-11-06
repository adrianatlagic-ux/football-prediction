from api import app as api
from scripts.log_bets import _build_entry


def test_model_disagreement_is_logged_but_does_not_replace_ai_pick():
    pick = {'market': '1X2', 'outcome': 'home_win', 'team': 'A',
            'best_odds': 2.05, 'market_probability': .48,
            'model_probability_raw': .43, 'quote_fresh': True}
    alternative = {**pick, 'market': 'Handicap +0.5', 'best_odds': 1.4,
                   'market_probability': .7, 'model_probability_raw': .75}
    vb = {'home_team': 'A', 'away_team': 'B', 'bets': [pick, alternative]}
    out = api._bet_tip(vb, {'pick': pick, 'revised_from_previous': False})
    assert out['tip'] is pick and out['status'] == 'ok' and out['confirmed']
    assert out['model_agrees'] is False and out['legacy_model_would_block']
    entry = _build_entry({**vb, 'bet_tip': out}, '2026-11-04T18:30:00Z')
    assert entry['bet_tip']['tip'] == pick
    assert entry['bet_tip']['legacy_model_would_block']
    assert entry['bets'] == [pick, alternative]


def test_quote_and_ai_review_still_control_publication():
    pick = {'market': '1X2', 'outcome': 'home_win', 'team': 'A',
            'best_odds': 1.8, 'market_probability': .55,
            'model_probability_raw': .49, 'quote_fresh': True}
    vb = {'home_team': 'A', 'away_team': 'B', 'bets': [pick]}
    assert api._bet_tip(vb, {'pick': pick, 'revised_from_previous': True})['status'] == 'ai_unsure'
    assert api._bet_tip(vb, {'pick': {**pick, 'best_odds': 1.29}})['tip'] is None
    assert api._bet_tip(vb, {'pick': {**pick, 'quote_fresh': False}})['tip'] is None

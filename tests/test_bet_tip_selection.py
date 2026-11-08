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
    assert api._bet_tip(vb, {'pick': pick, 'revised_from_previous': True})['tip'] is pick
    assert api._bet_tip(vb, {'pick': {**pick, 'best_odds': 1.29}})['tip'] is None
    assert api._bet_tip(vb, {'pick': {**pick, 'quote_fresh': False}})['tip'] is None


def test_reasoned_change_is_logged_and_available_for_combos():
    from src.combo_ticket import combo_report
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    pairs = []
    for home, away in [('A', 'B'), ('C', 'D')]:
        old = {'market': '1X2', 'outcome': 'away_win', 'team': away}
        pick = {'market': '1X2', 'outcome': 'home_win', 'team': home,
                'best_odds': 1.8, 'market_probability': .55, 'model_probability_raw': .49,
                'probability': .52, 'quote_fresh': True, 'bookmaker': 'Test', 'bookmaker_key': 'test'}
        vb = {'home_team': home, 'away_team': away, 'bets': [pick], 'odds_found': True,
              'snapshot_valid': True, 'sport_key': 'soccer_uefa_champs_league',
              'commence_time': (now + timedelta(minutes=30)).isoformat()}
        agent = {'pick': pick, 'first_pick': old, 'revised_from_previous': True,
                 'change_reason': 'Neue Startelf bestätigt wichtige Ausfälle.'}
        out = api._bet_tip(vb, agent)
        assert out['tip'] is pick and out['confirmed'] and out['revised']
        assert out['first_pick'] == old and out['change'] == 'changed_mind'
        entry = _build_entry({**vb, 'agent_eval': agent, 'bet_tip': out}, now.isoformat())
        assert entry['agent_eval']['first_pick'] == old
        assert entry['bet_tip']['change_reason'] == agent['change_reason']
        assert api._bet_tip(vb, {**agent, 'change_reason': '   '})['tip'] is pick
        assert api._bet_tip(vb, {**agent, 'pick': {**pick, 'quote_fresh': False}})['tip'] is None
        assert api._bet_tip({**vb, 'in_play': True}, agent)['tip'] is None
        pairs.append(({}, {**vb, 'published_ai_pick': out['tip'], 'agent_revised': True}))
    report = combo_report(pairs, policy='ai_pick', allow_mixed_books=True)
    assert report['recommended']['leg_count'] == 2

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import json

import pytest
from api import app as api
from src.ai_tip_research import VERSION, coverage, fresh_candidates, input_snapshot, market_changes


def bet(market, outcome, team=None, odds=1.8):
    return {'market': market, 'outcome': outcome, 'team': team, 'best_odds': odds,
            'quote_fresh': True, 'model_probability_raw': .65, 'market_probability': .55}


def fixture():
    bets = [bet('1X2', 'home_win', 'A'), bet('1X2', 'draw'), bet('1X2', 'away_win', 'B'),
            bet('Handicap -1.5', 'handicap', 'A'), bet('Handicap +1.5', 'handicap', 'B'),
            bet('Over/Under 2.5', 'Over'), bet('Over/Under 2.5', 'Under')]
    return {'home_team': 'A', 'away_team': 'B', 'bets': bets,
            'green_bets': [bets[-2]], 'red_bets': [],
            'sport_key': 'soccer_germany_bundesliga', 'event_id': 'test',
            'commence_time': '2026-10-24T13:30:00Z', 'odds_fetched_at': '2026-10-24T12:40:00Z',
            'model_favorite': bets[0]}


def prediction():
    return {'probability_home_win': .51, 'probability_draw': .27,
            'probability_away_win': .22,
            'score_prediction': {'home_xg': 1.62, 'away_xg': .91},
            'prediction_label': 'Home Win'}


def fake_gemini(monkeypatch, answer):
    from google import genai
    from src import gemini_usage
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps(answer), candidates=[])
    monkeypatch.setattr(api, 'GEMINI_API_KEY', 'test')
    monkeypatch.setattr(genai, 'Client', lambda **kw: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(gemini_usage, 'record', lambda *a, **kw: None)
    return calls


def answer(market='1X2', outcome='A'):
    return {'research': {'form': 'A zuletzt stabil.'}, 'pick_market': market,
            'pick_outcome': outcome, 'bet_headline': 'Sieg A',
            'bet_reasoning': 'Gute Form.', 'bet_points': [],
            'alternative_reasoning': 'Besser als Über.', 'change_reason': 'Neue Quote.'}


def test_full_market_and_compact_model_enter_existing_one_call(monkeypatch):
    vb = fixture()
    calls = fake_gemini(monkeypatch, answer())
    result = api._call_gemini_agent_pick(prediction(), vb, 'A', 'B')
    assert len(calls) == 1
    assert calls[0]['model'] == 'gemini-3.8-flash'
    assert result['pick'] == vb['bets'][0]
    assert api._bet_tip(vb, result)['tip'] == vb['bets'][0]
    assert len(result['research_input']['candidates']) == len(vb['bets'])
    assert result['research_input']['model_context']['home_xg'] == 1.62
    assert result['research_version'] == VERSION
    assert result['alternative_reasoning'] == 'Besser als Über.'
    rendered = calls[0]['contents']
    assert 'STEP 1 - RESEARCH (use Google Search)' in rendered
    assert '2026-10-24T13:30:00Z' in rendered
    assert 'Expected goals: 1.62 for A, 0.91 for B' in rendered
    assert 'market=1X2, outcome=A' in rendered
    assert 'market=Over/Under 2.5, outcome=Under' in rendered
    assert 'model_favorite' not in rendered
    assert 'green_bets' not in rendered


def test_order_and_model_bet_scores_do_not_change_inputs():
    vb = fixture()
    now = datetime(2026, 10, 24, 12, 45, tzinfo=timezone.utc)
    original = input_snapshot(vb, fresh_candidates(vb), prediction(), now)
    modified = deepcopy(vb)
    modified['bets'].reverse()
    modified['green_bets'] = []
    modified['red_bets'] = [{'secret': 'DO NOT LEAK'}]
    for item in modified['bets']:
        item.update(expected_value=500, probability=.999, model_probability_raw=.999, kelly_stake_pct=99)
    assert input_snapshot(modified, fresh_candidates(modified), prediction(), now) == original
    assert coverage(fresh_candidates(vb))['complete']


@pytest.mark.parametrize('missing', ['1X2', 'Handicap', 'Over/Under'])
def test_incomplete_book_defers_existing_call_and_tip(monkeypatch, missing):
    vb = fixture()
    vb['bets'] = [item for item in vb['bets'] if not item['market'].startswith(missing)]
    calls = fake_gemini(monkeypatch, answer())
    result = api._call_gemini_agent_pick(prediction(), vb, 'A', 'B')
    assert result['status'] == 'incomplete_markets'
    assert missing in result['research_input']['coverage']['missing_main_markets']
    assert not calls
    assert api._bet_tip(vb, result)['status'] == 'incomplete_markets'


def test_stale_or_one_sided_markets_do_not_count_as_coverage():
    vb = fixture()
    vb['bets'][-1]['quote_fresh'] = False
    vb['bets'][4]['team'] = 'A'
    assert coverage(fresh_candidates(vb))['missing_main_markets'] == ['Handicap', 'Over/Under']
    assert coverage(fresh_candidates(fixture()))['complete']


def test_different_handicap_lines_for_both_teams_count_as_coverage():
    vb = fixture()
    vb['bets'][3]['market'] = 'Handicap +0.5'
    vb['bets'][4]['market'] = 'Handicap +0.5'
    assert coverage(fresh_candidates(vb))['complete']


def test_recheck_can_change_on_new_markets_or_odds_and_records_prior_input(monkeypatch):
    vb = fixture()
    first_calls = fake_gemini(monkeypatch, answer('Over/Under 2.5', 'Over'))
    first = api._call_gemini_agent_pick(prediction(), vb, 'A', 'B')
    assert len(first_calls) == 1
    changed = deepcopy(vb)
    changed['bets'][0]['best_odds'] = 2.05
    second_calls = fake_gemini(monkeypatch, answer())
    second = api._call_gemini_agent_pick(prediction(), changed, 'A', 'B', previous_eval=first)
    assert len(second_calls) == 1
    assert 'changed odds' in second_calls[0]['contents']
    assert '1.8 -> 2.05' in second_calls[0]['contents']
    assert second['revised_from_previous'] is True
    assert second['first_pick'] == vb['bets'][-2]
    assert second['first_research_input'] == first['research_input']
    assert second['change_reason'] == 'Neue Quote.'
    assert api._bet_tip(changed, second)['status'] == 'ai_unsure'


def test_first_complete_review_after_missing_markets_is_not_change(monkeypatch):
    vb = fixture()
    calls = fake_gemini(monkeypatch, answer())
    incomplete = {**vb, 'bets': vb['bets'][:3]}
    previous = api._call_gemini_agent_pick(prediction(), incomplete, 'A', 'B')
    result = api._call_gemini_agent_pick(prediction(), vb, 'A', 'B', previous_eval=previous)
    assert len(calls) == 1
    assert result['revised_from_previous'] is None
    assert api._bet_tip(vb, result)['status'] == 'ok'


def test_market_change_summary_detects_new_and_removed_outcomes():
    vb = fixture()
    previous = input_snapshot(vb, fresh_candidates(vb), prediction())
    later = deepcopy(vb)
    later['bets'].append(bet('BTTS', 'yes'))
    later['bets'][0]['quote_fresh'] = False
    changes = market_changes(previous, input_snapshot(later, fresh_candidates(later), prediction()))
    assert changes['added'] == ['BTTS / yes @1.8']
    assert changes['removed'] == ['1X2 / A @1.8']


def test_no_pick_and_snapshot_reach_bet_log(monkeypatch):
    from scripts.log_bets import _build_entry
    vb = fixture()
    fake_gemini(monkeypatch, answer(None, None))
    result = api._call_gemini_agent_pick(prediction(), vb, 'A', 'B')
    entry = _build_entry({**vb, 'agent_eval': result}, '2026-10-24T12:45:00Z')
    assert entry['agent_eval']['research_input']['candidates']
    assert entry['agent_eval']['prompt_text']
    assert api._bet_tip(vb, result)['status'] == 'no_selection'

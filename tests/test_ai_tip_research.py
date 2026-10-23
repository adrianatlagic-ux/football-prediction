from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import json

import pytest
from api import app as api
from src.ai_tip_research import VERSION, fresh_candidates, coverage, input_snapshot, prompt


def bet(market, outcome, team=None):
    return {'market': market, 'outcome': outcome, 'team': team, 'best_odds': 1.8,
            'quote_fresh': True, 'model_probability_raw': .65, 'market_probability': .55}


def fixture():
    bets = [bet('1X2', 'home_win', 'A'), bet('1X2', 'draw'), bet('1X2', 'away_win', 'B'),
            bet('Handicap -1.5', 'handicap', 'A'), bet('Handicap +1.5', 'handicap', 'B'),
            bet('Over/Under 2.5', 'Over'), bet('Over/Under 2.5', 'Under')]
    return {'home_team': 'A', 'away_team': 'B', 'bets': bets,
            'green_bets': bets[-2:], 'red_bets': [],
            'sport_key': 'soccer_germany_bundesliga', 'event_id': 'test',
            'commence_time': '2026-10-24T13:30:00Z', 'odds_fetched_at': '2026-10-24T12:40:00Z',
            'model_favorite': bets[0]}


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


def test_full_book_reaches_ai_even_when_not_in_green_red_shortlist(monkeypatch):
    vb = fixture()
    calls = fake_gemini(monkeypatch, {'pick_market': '1X2', 'pick_outcome': 'A'})
    result = api._call_gemini_agent_pick({}, vb, 'A', 'B')
    assert result['pick'] == vb['bets'][0]
    assert len(result['research_input']['candidates']) == 7
    assert result['research_version'] == VERSION
    assert '2026-10-24T13:30:00Z' in calls[0]['contents']
    assert 'market_comparison' in calls[0]['contents']
    assert 'published_at' in calls[0]['contents']


def test_model_scores_shortlists_and_order_do_not_affect_ai_prompt():
    vb = fixture()
    now = datetime(2026, 10, 24, 12, 45, tzinfo=timezone.utc)
    def render(v):
        return prompt(input_snapshot(v, fresh_candidates(v), now), 'A', 'B', 'Bundesliga')
    original = render(vb)
    modified = deepcopy(vb)
    modified['bets'].reverse()
    modified['green_bets'] = []
    modified['red_bets'] = [{'secret': 'DO NOT LEAK'}]
    for b in modified['bets']:
        b.update(expected_value=500, probability=.999, model_probability_raw=.999, kelly_stake_pct=99)
    assert render(modified) == original


def test_recheck_is_blind_to_previous_pick_but_records_change(monkeypatch):
    vb = fixture()
    original_input = {'coverage': {'complete': True}, 'candidates': ['old snapshot']}
    previous = {'pick': vb['bets'][-2], 'bet_headline': 'SECRET OLD PICK',
                'bet_reasoning': 'KEEP MY OLD PICK', 'research_input': original_input}
    calls = fake_gemini(monkeypatch, {'pick_market': '1X2', 'pick_outcome': 'A'})
    result = api._call_gemini_agent_pick({}, vb, 'A', 'B', previous_eval=previous)
    assert 'SECRET OLD PICK' not in calls[0]['contents']
    assert 'KEEP MY OLD PICK' not in calls[0]['contents']
    assert result['revised_from_previous'] is True
    assert result['first_pick'] == previous['pick']
    assert result['first_research_input'] == original_input
    assert api._bet_tip(vb, result)['status'] == 'ai_unsure'


def test_unchanged_recheck_preserves_confirmation_and_model_gate(monkeypatch):
    vb = fixture()
    fake_gemini(monkeypatch, {'pick_market': '1X2', 'pick_outcome': 'A'})
    result = api._call_gemini_agent_pick({}, vb, 'A', 'B', previous_eval={'pick': vb['bets'][0]})
    assert result['revised_from_previous'] is False
    assert api._bet_tip(vb, result)['confirmed'] is True
    result['pick']['model_probability_raw'] = .2
    assert api._bet_tip(vb, result)['tip'] is None


@pytest.mark.parametrize('missing', ['1X2', 'Handicap', 'Over/Under'])
def test_missing_main_market_prevents_paid_call_and_tip(monkeypatch, missing):
    vb = fixture()
    vb['bets'] = [b for b in vb['bets'] if not b['market'].startswith(missing)]
    calls = fake_gemini(monkeypatch, {})
    result = api._call_gemini_agent_pick({}, vb, 'A', 'B')
    assert result['status'] == 'incomplete_markets'
    assert missing in result['research_input']['coverage']['missing_main_markets']
    assert not calls
    assert api._bet_tip(vb, result)['status'] == 'incomplete_markets'


def test_stale_or_one_sided_markets_do_not_count_as_coverage():
    vb = fixture()
    vb['bets'][-1]['quote_fresh'] = False
    vb['bets'][4]['market'] = 'Handicap +2.5'
    assert coverage(fresh_candidates(vb))['missing_main_markets'] == ['Handicap', 'Over/Under']
    assert coverage(fresh_candidates(fixture()))['complete']
    # BTTS is optional: its outage does not suppress a complete main book.
    assert not coverage(fresh_candidates(fixture()))['available']['BTTS']


def test_current_coverage_can_withhold_a_previously_accepted_pick():
    vb = fixture()
    agent = {'pick': vb['bets'][0], 'research_input': input_snapshot(vb, fresh_candidates(vb))}
    vb['bets'][-1]['quote_fresh'] = False
    assert api._bet_tip(vb, agent)['status'] == 'incomplete_markets'


def test_no_pick_and_evidence_survive_logging(monkeypatch):
    from scripts.log_bets import _build_entry
    vb = fixture()
    facts = [{'claim': 'Reported injury', 'source_url': 'https://club.example/news',
              'published_at': '2026-10-01T12:00:00Z', 'status': 'reported'}]
    fake_gemini(monkeypatch, {'pick_market': None, 'pick_outcome': None, 'facts': facts,
                             'market_comparison': [{'market_family': '1X2', 'assessment': 'uncertain'}],
                             'alternative_reasoning': 'Keine ausreichend begründete Auswahl.'})
    result = api._call_gemini_agent_pick({}, vb, 'A', 'B')
    entry = _build_entry({**vb, 'agent_eval': result}, '2026-10-24T12:45:00Z')
    assert result['pick'] is None
    assert entry['agent_eval']['evidence']['facts'][0]['verified'] is False
    assert entry['agent_eval']['research_input']['candidates']
    assert entry['agent_eval']['alternative_reasoning']


def test_first_complete_review_after_missing_markets_is_not_a_changed_pick(monkeypatch):
    vb = fixture()
    calls = fake_gemini(monkeypatch, {'pick_market': '1X2', 'pick_outcome': 'A'})
    incomplete = {**vb, 'bets': vb['bets'][:3]}
    previous = api._call_gemini_agent_pick({}, incomplete, 'A', 'B')
    result = api._call_gemini_agent_pick({}, vb, 'A', 'B', previous_eval=previous)
    assert len(calls) == 1
    assert result['revised_from_previous'] is None
    assert api._bet_tip(vb, result)['status'] == 'ok'
    assert not api._bet_tip(vb, result)['confirmed']


def test_intentional_no_bet_does_not_claim_research_is_still_pending(monkeypatch):
    vb = fixture()
    fake_gemini(monkeypatch, {'pick_market': None})
    result = api._call_gemini_agent_pick({}, vb, 'A', 'B')
    assert api._bet_tip(vb, result)['status'] == 'no_selection'

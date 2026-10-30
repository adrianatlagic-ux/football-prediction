import json
from types import SimpleNamespace

import pytest

from api import app as api
from src.ai_tip_research import VERSION


@pytest.mark.parametrize('legacy_recheck', [False, True])
def test_agent_does_not_receive_model_outputs_even_via_old_reasoning(monkeypatch, legacy_recheck):
    from google import genai
    from src import gemini_usage

    captured = []
    response = SimpleNamespace(text=json.dumps({
        'pick_market': 'Over/Under 3.5', 'pick_outcome': 'Under',
        'bet_headline': 'Unter 3,5 Tore', 'bet_reasoning': 'Die recherchierte Aufstellung spricht dafür.'
    }), candidates=[])
    def generate_content(**kwargs):
        captured.append(kwargs['contents'])
        return response
    monkeypatch.setattr(api, 'GEMINI_API_KEY', 'test-placeholder')
    monkeypatch.setattr(genai, 'Client', lambda **kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(gemini_usage, 'record', lambda *args, **kwargs: None)
    bets = []
    for market, outcome, team in [
        ('1X2', 'home_win', 'Alpha'), ('1X2', 'draw', None), ('1X2', 'away_win', 'Bravo'),
        ('Handicap +0.5', 'handicap', 'Alpha'), ('Handicap +0.5', 'handicap', 'Bravo'),
        ('Over/Under 3.5', 'Over', None), ('Over/Under 3.5', 'Under', None),
    ]:
        bets.append({'market': market, 'outcome': outcome, 'team': team, 'best_odds': 1.8,
                     'quote_fresh': True, 'model_probability_raw': .9123456789,
                     'probability': .9123456789, 'market_probability': .55})
    vb = {'bets': bets, 'commence_time': '2099-10-30T19:30:00Z', 'odds_fetched_at': '2099-10-30T06:00:00Z'}
    prediction = {'probability_home_win': .9123456789,
                  'score_prediction': {'home_xg': 99.987654321},
                  'explanation': {'form': 'INTERNAL_MODEL_SENTINEL'}}
    previous = None
    if legacy_recheck:
        previous = {'pick': bets[-1], 'bet_headline': 'INTERNAL_MODEL_SENTINEL',
                    'bet_reasoning': 'INTERNAL_MODEL_SENTINEL model probability 91.23456789%',
                    'research_version': 'full_market_model_context_v4'}
    result = api._call_gemini_agent_pick(prediction, vb, 'Alpha', 'Bravo', previous_eval=previous)
    assert result is not None and len(captured) == 1
    prompt = captured[0]
    for secret in ['INTERNAL_MODEL_SENTINEL', '0.9123456789', '99.987654321', '91.23456789',
                   'OUR QUANTITATIVE MODEL ANALYSIS']:
        assert secret not in prompt
    assert 'model_context' not in result['research_input']
    assert result['research_version'] == VERSION
    # The selected bet still carries backend-only values for the later gate.
    assert result['pick']['model_probability_raw'] == .9123456789

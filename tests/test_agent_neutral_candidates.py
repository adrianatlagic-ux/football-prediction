import json
import sys
from types import SimpleNamespace


def test_market_baseline_does_not_change_ai_prompt(monkeypatch):
    from api import app as api
    from src import gemini_usage

    prompts = []
    def generate(**kwargs):
        prompts.append(kwargs['contents'])
        return SimpleNamespace(text=json.dumps({'pick_market': '1X2', 'pick_outcome': 'A'}), candidates=[])
    fake = SimpleNamespace(
        Client=lambda **kw: SimpleNamespace(models=SimpleNamespace(generate_content=generate)),
        types=SimpleNamespace(Tool=lambda **kw: kw, GoogleSearch=lambda: {},
                              GenerateContentConfig=lambda **kw: kw))
    monkeypatch.setitem(sys.modules, 'google', SimpleNamespace(genai=fake))
    monkeypatch.setitem(sys.modules, 'google.genai', fake)
    monkeypatch.setattr(api, 'GEMINI_API_KEY', 'test-only')
    monkeypatch.setattr(gemini_usage, 'record', lambda *a, **kw: None)
    bets = [dict(market=m, outcome=o, team=t, best_odds=2.0,
                 quote_fresh=True, market_probability=.5)
            for m, o, t in [('1X2', 'home_win', 'A'), ('1X2', 'away_win', 'B'),
                            ('1X2', 'draw', None), ('Handicap +0.5', 'handicap', 'A'),
                            ('Handicap -0.5', 'handicap', 'B'),
                            ('Over/Under 2.5', 'Over', None), ('Over/Under 2.5', 'Under', None)]]
    vb = dict(bets=bets, commence_time='2026-11-08T18:00:00Z')
    for baseline in [bets[0], bets[-1]]:
        result = api._call_gemini_agent_pick({}, dict(vb, likely_pick=baseline), 'A', 'B')
        assert result['pick'] == bets[0]
        assert result['research_version'] == 'market_research_neutral_v8'
        # The comparison stays in the audit snapshot, not in the AI prompt.
        assert result['research_input']['market_baseline']['market'] == baseline['market']
    assert prompts[0] == prompts[1]
    assert 'MARKET COMPARISON' not in prompts[0]
    for bet in bets:
        line = f"- market={bet['market']}, outcome={bet.get('team') or bet['outcome']}, odds=2.0"
        assert prompts[0].count(line) == 1
    old = dict(pick=bets[0], bet_headline='A gewinnt', research_version='market_research_baseline_v7',
               bet_reasoning='OLD_BASELINE_REASONING')
    result = api._call_gemini_agent_pick({}, vb, 'A', 'B', previous_eval=old)
    assert result is not None
    assert 'OLD_BASELINE_REASONING' not in prompts[-1]

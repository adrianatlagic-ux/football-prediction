"""The agent prompt (v9): model context in, value framing and price moves out."""
import json
from types import SimpleNamespace


def _bet(market, outcome, team, odds, model_p, market_p):
    return {"market": market, "outcome": outcome, "team": team, "best_odds": odds, "quote_fresh": True,
            "model_probability_raw": model_p, "market_probability": market_p}


VB = {"sport_key": "soccer_uefa_nations_league", "commence_time": "2026-11-14T19:45:00Z",
      "odds_fetched_at": "2026-11-14T18:00:00Z", "bets": [
          _bet("1X2", "home_win", "Alpha", 1.5, .70, .64), _bet("1X2", "draw", None, 4.0, .18, .24),
          _bet("1X2", "away_win", "Bravo", 7.0, .12, .13),
          _bet("Handicap -1.5", "handicap", "Alpha", 2.3, .38, .42),
          _bet("Handicap +1.5", "handicap", "Bravo", 1.6, .62, .58),
          _bet("Over/Under 2.5", "Over", None, 1.9, .51, .51), _bet("Over/Under 2.5", "Under", None, 1.9, .49, .49)]}
PREDICTION = {"probability_home_win": .70, "probability_draw": .18, "probability_away_win": .12,
              "score_prediction": {"home_xg": 1.9, "away_xg": .7, "most_likely_score": "2:0"}}
ANSWER = {"research": {}, "pick_market": "1X2", "pick_outcome": "Alpha", "bet_headline": "Sieg Alpha",
          "bet_reasoning": "x", "bet_points": [], "alternative_reasoning": "", "change_reason": ""}


def _run(monkeypatch, previous=None):
    from api import app as api
    import google.genai as genai

    prompts = []

    class Models:
        def generate_content(self, model, contents, config):
            prompts.append(contents)
            return SimpleNamespace(text=json.dumps(ANSWER), candidates=[], usage_metadata=None)

    monkeypatch.setattr(api, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(genai, "Client", lambda api_key: SimpleNamespace(models=Models()))
    result = api._call_gemini_agent_pick(PREDICTION, VB, "Alpha", "Bravo", previous_eval=previous)
    return prompts[0], result


def test_the_prompt_shows_the_model_and_asks_for_football_reasons(monkeypatch):
    prompt, result = _run(monkeypatch)
    assert '"most_likely_score":"2:0"' in prompt
    assert "market=1X2, outcome=Alpha, odds=1.5, our model 70% / market 64%" in prompt
    assert "value-betting" not in prompt
    assert "bet_points" not in prompt and "bet_points" not in result
    assert result["research_input"]["model_context"]["home_xg"] == 1.9
    assert result["research_version"] == "football_research_model_v9"


def test_the_re_check_hears_about_new_markets_but_not_price_moves(monkeypatch):
    from src.ai_tip_research import input_snapshot
    earlier = dict(VB, bets=[dict(b, best_odds=b["best_odds"] + .1) for b in VB["bets"]
                             if b["market"] != "Handicap -1.5"])
    previous = {"bet_headline": "Sieg Alpha", "pick": VB["bets"][0], "research_version": "football_research_model_v9",
                "bet_reasoning": "x", "research_input": input_snapshot(earlier, earlier["bets"])}
    prompt, _ = _run(monkeypatch, previous)
    assert "Handicap -1.5 / Alpha @2.3" in prompt      # newly available market
    assert "1.6 -> 1.5" not in prompt and "changed" not in prompt

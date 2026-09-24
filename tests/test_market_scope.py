"""Only genuinely offered half lines reach the current tip UI."""
import pytest
from api import app as api
from tests.test_bet_selection import event, prediction
from src.combo_ticket import combo_report, leg_pool


@pytest.mark.parametrize("line", [-1.75, -.75, -.25, .25, .75, 2.25])
def test_offered_quarter_lines_never_reach_suggestions(line):
    e = event()
    e["bookmakers"][0]["markets"] = [
        {"key": "spreads", "outcomes": [{"name": "A", "point": line, "price": 1.9},
                                          {"name": "B", "point": -line, "price": 1.9}]},
        {"key": "totals", "outcomes": [{"name": "Over", "point": abs(line), "price": 1.9},
                                         {"name": "Under", "point": abs(line), "price": 1.9}]},
    ]
    result = api._compute_value_bets(prediction(), [e], "A", "B", include_offers=True)
    assert result["bets"] == []
    assert result["recommendation"] is None
    assert result["market_favorite"] is None
    assert leg_pool([(prediction(), result)]) == []


def test_only_offered_supported_lines_are_kept():
    e = event()
    e["bookmakers"][0]["markets"] += [
        {"key": "totals", "outcomes": [{"name": "Over", "point": 2.5, "price": 1.8},
                                         {"name": "Under", "point": 2.5, "price": 2.1}]},
        {"key": "spreads", "outcomes": [{"name": "A", "point": 1.5, "price": 1.3},
                                          {"name": "B", "point": -1.5, "price": 3.4}]},
    ]
    result = api._compute_value_bets(prediction(), [e], "A", "B", include_offers=True)
    markets = {b["market"] for b in result["bets"]}
    assert markets == {"1X2", "Handicap +1.5", "Handicap -1.5", "Over/Under 2.5"}
    over = next(b for b in result["bets"] if b["market"] == "Over/Under 2.5" and b["outcome"] == "Over")
    assert over["best_odds"] == 1.8
    assert all(o["best_odds"] == 1.8 for o in over["bookmaker_offers"])


def test_live_selections_do_not_call_the_experimental_selector(monkeypatch):
    import src.game_pick as old_selector
    def reject(*args, **kwargs):
        pytest.fail("The removed experimental selector was called")
    monkeypatch.setattr(old_selector, "assess", reject)
    monkeypatch.setattr(old_selector, "select_game_pick", reject)
    result = api._compute_value_bets(prediction(), [event()], "A", "B", include_offers=True)
    assert api._combine_recommendation(result, None)["consensus_pick"] == result["market_favorite"]
    assert combo_report([(prediction(), result)])["parameters"]["single_bet_stress_required"] is False

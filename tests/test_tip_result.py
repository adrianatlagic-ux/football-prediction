"""How the AI tip of a finished match turned out (GET /ai-tip-result)."""
from src import match_memory
from src.tip_result import tip_result

NL = "soccer_uefa_nations_league"
TIP = {"market": "Handicap +1.5", "outcome": "handicap", "team": "Bosnia & Herzegovina", "best_odds": 1.69,
       "market_probability": 0.57}
ENTRY = {"home_team": "Sweden", "away_team": "Bosnia & Herzegovina", "commence_time": "2026-11-14T19:45:00Z",
         "sport_key": NL, "competition": "Nations League", "result": {"home_score": 3, "away_score": 2},
         "agent_eval": {"pick": TIP, "bet_headline": "Bosnien +1,5", "bet_reasoning": "**ungeschlagen**"},
         "bets": [TIP, {**TIP, "best_odds": 1.6},
                  {"market": "1X2", "outcome": "home_win", "team": "Sweden", "best_odds": 1.49, "market_probability": 0.64},
                  {"market": "Over/Under 2.5", "outcome": "Under", "team": None, "best_odds": 2.3, "market_probability": 0.4}]}


def test_the_tip_and_every_bet_are_graded_in_the_pages_spelling():
    # The page's fixture says "Bosnia and Herzegovina" and dates the match by local time.
    r = tip_result("Sweden", "Bosnia and Herzegovina", "2026-11-15", entries=[ENTRY], cases=[])
    assert r["found"] and r["tip"]["result"] == "win" and r["tip"]["team"] == "Bosnia and Herzegovina"
    assert [(b["market"], b["result"]) for b in r["bets"]] == [
        ("1X2", "win"), ("Handicap +1.5", "win"), ("Over/Under 2.5", "loss")]
    assert next(b for b in r["bets"] if b["market"] == "Handicap +1.5")["best_odds"] == 1.69   # best odds, once
    assert r["review"] is None


def test_the_review_comes_from_the_memory_case():
    case = {"id": match_memory.case_id(ENTRY), "what_decided": "Doppelschlag nach der Pause",
            "luck_or_reasoning": "mixed", "luck_explanation": "0:3 zur Pause", "arguments": []}
    r = tip_result("Sweden", "Bosnia and Herzegovina", "2026-11-14", entries=[ENTRY], cases=[case])
    assert r["review"]["what_decided"] == "Doppelschlag nach der Pause"


def test_no_result_for_an_open_or_unknown_match():
    open_match = {**ENTRY, "result": None}
    assert tip_result("Sweden", "Bosnia and Herzegovina", "2026-11-14", entries=[open_match], cases=[]) == {"found": False}
    assert tip_result("Spain", "England", "2026-11-14", entries=[ENTRY], cases=[]) == {"found": False}

import json



def _entry(date, home="Germany", away="Greece"):
    return {"home_team": home, "away_team": away, "commence_time": f"{date}T18:45:00Z",
            "sport_key": "soccer_uefa_nations_league",
            "bets": [{"market": "1X2", "outcome": "win", "team": "Germany", "model_probability_raw": 0.7,
                      "market_probability": 0.6}]}


def test_the_logger_fills_an_entry_that_was_logged_without_odds():
    from datetime import datetime, timezone
    from scripts.log_bets import apply
    empty = {**_entry("2026-09-10"), "bets": []}
    entries = [empty]
    match = {"home_team": "Germany", "away_team": "Greece", "commence_time": "2026-09-10T18:45:00Z",
             "sport_key": "soccer_uefa_nations_league",
             "bets": [{"market": "1X2", "outcome": "win", "team": "Germany", "probability": .7}]}
    added, updated = apply([match], entries, datetime(2026, 9, 10, 18, 30, tzinfo=timezone.utc))
    assert (added, updated) == (0, 1) and entries[0]["bets"]


def test_new_entries_no_longer_carry_the_dropped_categories():
    from datetime import datetime, timezone
    from scripts.log_bets import _build_entry
    entry = _build_entry({"home_team": "A", "away_team": "B", "sport_key": "soccer_uefa_nations_league",
                          "green_bets": [1], "red_bets": [2], "recommendation": {"market": "1X2"},
                          "safest_pick": {}, "bet_tip_v1": {}, "price_tip": {}, "bet_tip": {"tip": None},
                          "model_favorite": {}, "likely_pick": {}, "combined": {}, "agent_eval": {}, "bets": []},
                         datetime(2026, 11, 14, tzinfo=timezone.utc).isoformat())
    for dropped in ("green_bets", "red_bets", "recommendation", "recommendation_warning", "safest_pick",
                    "bet_tip_v1", "price_tip"):
        assert dropped not in entry
    for kept in ("bet_tip", "model_favorite", "likely_pick", "combined", "agent_eval", "bets"):
        assert kept in entry

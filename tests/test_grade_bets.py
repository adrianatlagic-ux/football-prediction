from scripts.grade_bets import competition_of, grade_entries


def _entry(sport_key, game_odds, likely_odds, likely_market="Over/Under 2.5", likely_outcome="Over"):
    game = {"market": "1X2", "outcome": "win", "team": "A", "best_odds": game_odds}
    return {"home_team": "A", "away_team": "B", "commence_time": "2026-10-01T18:45:00Z", "sport_key": sport_key,
            "green_bets": [], "red_bets": [game], "combined": {"consensus_pick": game},
            "likely_pick": {"market": likely_market, "outcome": likely_outcome, "team": None,
                            "best_odds": likely_odds}}


FINISHED = {("a", "b", "2026-10-01"): {"home_score": 1, "away_score": 0}}


def test_competitions_are_named_from_the_sport_key_and_old_entries_kept_apart():
    assert competition_of({"sport_key": "soccer_uefa_nations_league"}) == "Nations League"
    assert competition_of({"sport_key": "soccer_germany_bundesliga"}) == "Bundesliga"
    assert competition_of({}) == "ohne Wettbewerb (alte Einträge)"


def test_the_fair_comparison_uses_only_matches_with_both_picks_in_the_same_odds_range():
    inside = grade_entries([_entry("x", 1.60, 1.50)], FINISHED)
    assert inside["fair_matches"] == 1
    assert inside["buckets"]["fair_game"].wins == 1          # A won 1:0
    assert inside["buckets"]["fair_likely"].losses == 1       # over 2.5 lost
    # A Game Pick at 1.20 lies outside 🎯's range: not compared.
    outside = grade_entries([_entry("x", 1.20, 1.50)], FINISHED)
    assert outside["fair_matches"] == 0 and outside["buckets"]["consensus"].wins == 1


def test_results_are_matched_on_the_date_too():
    other_day = {("a", "b", "2026-11-12"): {"home_score": 0, "away_score": 2}}
    assert grade_entries([_entry("x", 1.60, 1.50)], other_day)["pending"] == 1

from scripts.log_bets import _fixture_key


def test_log_identity_keeps_return_fixtures_separate():
    first = {"home_team": "Alpha", "away_team": "Bravo", "commence_time": "2026-09-01T18:00:00Z",
             "sport_key": "soccer_test", "event_id": "match-1"}
    return_leg = {**first, "commence_time": "2027-02-01T18:00:00Z", "event_id": "match-2"}
    assert _fixture_key(first) != _fixture_key(return_leg)

import json

from scripts.build_model_track_record import grade_live


def _entry(date, home="Germany", away="Greece"):
    return {"home_team": home, "away_team": away, "commence_time": f"{date}T18:45:00Z",
            "sport_key": "soccer_uefa_nations_league",
            "bets": [{"market": "1X2", "outcome": "win", "team": "Germany", "model_probability_raw": 0.7,
                      "market_probability": 0.6}]}


def _result(date, hs, as_):
    return {"home_team": "Germany", "away_team": "Greece", "commence_time": f"{date}T18:45Z",
            "completed": True, "home_score": hs, "away_score": as_}


def test_a_repeat_meeting_is_graded_against_its_own_date(tmp_path):
    log = tmp_path / "bet_log.jsonl"
    log.write_text(json.dumps(_entry("2026-09-10")) + "\n" + json.dumps(_entry("2026-10-14")) + "\n")
    # Only the first meeting has been played, and Germany lost it.
    cases = grade_live([log], [_result("2026-09-10", 0, 1)])
    assert len(cases) == 1 and cases[0]["won"] is False


def test_the_server_log_overrides_the_committed_copy(tmp_path):
    repo, server = tmp_path / "repo.jsonl", tmp_path / "server.jsonl"
    repo.write_text(json.dumps(_entry("2026-09-10")) + "\n")
    server.write_text(json.dumps(_entry("2026-09-10")) + "\n" + json.dumps(_entry("2026-10-14")) + "\n")
    cases = grade_live([repo, server], [_result("2026-09-10", 2, 0), _result("2026-10-14", 1, 0)])
    assert len(cases) == 2 and all(c["won"] for c in cases)


def test_an_entry_logged_without_odds_never_replaces_one_with_bets(tmp_path):
    repo, server = tmp_path / "repo.jsonl", tmp_path / "server.jsonl"
    repo.write_text(json.dumps(_entry("2026-09-10")) + "\n")
    server.write_text(json.dumps({**_entry("2026-09-10"), "bets": []}) + "\n")
    assert len(grade_live([repo, server], [_result("2026-09-10", 2, 0)])) == 1


def test_the_logger_fills_an_entry_that_was_logged_without_odds():
    from datetime import datetime, timezone
    from scripts.log_bets import apply
    empty = {**_entry("2026-09-10"), "bets": []}
    entries = [empty]
    match = {"home_team": "Germany", "away_team": "Greece", "commence_time": "2026-09-10T18:45:00Z",
             "sport_key": "soccer_uefa_nations_league",
             "green_bets": [{"market": "1X2", "outcome": "win", "team": "Germany", "probability": .7}]}
    added, updated = apply([match], entries, datetime(2026, 9, 10, 18, 30, tzinfo=timezone.utc))
    assert (added, updated) == (0, 1) and entries[0]["green_bets"]

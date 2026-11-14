import json

from scripts.migrate_logs import migrate
from src import log_store


def _tip(sport, home, day="2026-11-10"):
    return {"home_team": home, "away_team": "X", "commence_time": f"{day}T18:45:00Z", "sport_key": sport,
            "bets": [{"market": "1X2"}], "logged_at": f"{day}T18:20:00+00:00"}


def _combo(sport, day="2026-11-10", logged="2026-11-10T08:00:00+00:00"):
    leg = {"market": "1X2", "outcome": "home_win", "team": "A", "home_team": "A", "away_team": "B",
           "commence_time": f"{day}T18:45:00Z", "bookmaker_key": "b"}
    return {"competition": sport, "date": day, "policy": "market", "leg_count": 2, "quote_basis": "single_book",
            "first_kickoff": f"{day}T18:45:00+00:00", "logged_at": logged, "legs": [leg]}


def test_an_entry_goes_to_its_own_competition_file():
    assert log_store.slug({"sport_key": "soccer_germany_bundesliga"}) == "bundesliga"
    assert log_store.slug({"competition": "soccer_uefa_champs_league"}) == "champions-league"
    assert log_store.slug({"competition": "Nations League"}) == "nations-league"
    assert log_store.slug({"home_team": "A"}) == "sonstige"


def test_migration_splits_by_competition_keeps_everything_and_archives_the_original(tmp_path):
    logs = tmp_path / "logs"
    old = tmp_path / "bet_log.jsonl"
    old_combos = tmp_path / "combo_log.jsonl"
    tips = [_tip("soccer_germany_bundesliga", "A"), _tip("soccer_uefa_champs_league", "B"), {"home_team": "C", "away_team": "D", "commence_time": "2026-09-01T18:00:00Z", "bets": []}]
    old.write_text("".join(json.dumps(t) + "\n" for t in tips))
    old_combos.write_text("".join(json.dumps(c) + "\n" for c in (_combo("soccer_germany_bundesliga"), _combo("soccer_uefa_nations_league"))))
    original = old.read_text()

    result = migrate(logs, [old], [old_combos])

    assert result["matches"] == 3 and result["combos"] == 2
    assert [p.name for p in log_store.files("tips", logs)] == ["bundesliga.jsonl", "champions-league.jsonl", "sonstige.jsonl"]
    assert [p.name for p in log_store.files("combos", logs)] == ["bundesliga.jsonl", "nations-league.jsonl"]
    assert len(log_store.load_tips(logs)) == 3 and len(log_store.load_combos(logs)) == 2
    assert (logs / "archive" / "bet_log_full.jsonl").read_text() == original
    assert not old.exists() and not old_combos.exists()
    assert (logs / "README.md").exists()


def test_migrating_again_changes_nothing_and_a_second_old_file_is_merged(tmp_path):
    logs = tmp_path / "logs"
    first = tmp_path / "a.jsonl"
    first.write_text(json.dumps(_tip("soccer_germany_bundesliga", "A")) + "\n")
    migrate(logs, [first], [])
    before = log_store.as_text("tips", logs)
    assert migrate(logs, [first], []) == {"matches": 0, "combos": 0, "archived": []}
    assert log_store.as_text("tips", logs) == before
    # The server's own older-layout file holds the same match and a new one.
    server = tmp_path / "bet_log.jsonl"
    server.write_text(json.dumps(_tip("soccer_germany_bundesliga", "A")) + "\n"
                      + json.dumps(_tip("soccer_germany_bundesliga", "Z")) + "\n")
    assert migrate(logs, [server], [])["matches"] == 1
    assert len(log_store.load_tips(logs)) == 2


def test_the_logs_endpoint_serves_every_competition_under_old_and_new_names(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import app as api
    monkeypatch.setattr(log_store, "LOGS", tmp_path)
    log_store.write_tips([_tip("soccer_germany_bundesliga", "A"), _tip("soccer_uefa_champs_league", "B")], tmp_path)
    client = TestClient(api.app)
    for name in ("tips", "bet_log"):
        lines = client.get(f"/logs/{name}").text.splitlines()
        assert len(lines) == 2
    assert client.get("/logs/combos").text == ""
    assert client.get("/logs/other").status_code == 404

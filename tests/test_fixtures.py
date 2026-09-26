from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.fixtures import build

TZ = ZoneInfo("Europe/Berlin")


def _event(i, home, away, when, stage="2026-27-german-bundesliga"):
    return {"id": str(i), "date": when.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%MZ"),
            "season": {"slug": stage},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": home}},
                                              {"homeAway": "away", "team": {"displayName": away}}]}]}


def _round(start, pairs, offset=0):
    return [_event(offset + j, h, a, start + timedelta(hours=j)) for j, (h, a) in enumerate(pairs)]


TEAMS = [f"Team{c}" for c in "ABCDEFGHIJKL"]


def test_a_postponed_game_keeps_its_own_matchday_and_shifts_nothing():
    day1 = datetime(2026, 9, 5, 15, 30, tzinfo=TZ)
    r1 = [(TEAMS[i], TEAMS[i + 6]) for i in range(6)]
    r2 = [(TEAMS[i + 6], TEAMS[(i + 1) % 6]) for i in range(6)]
    events = _round(day1, r1[1:]) + _round(day1 + timedelta(days=7), r2, 10) \
        + [_event(99, *r1[0], day1 + timedelta(days=10))]          # matchday 1 game, played late
    fixtures = build("bl", today=day1.date(), events=events)
    groups = {(f["home_team"], f["away_team"]): f["group"] for f in fixtures}
    assert groups[r1[0]] == "Spieltag 1"
    assert all(groups[p] == "Spieltag 2" for p in r2)


def test_a_repeat_meeting_on_another_date_is_kept():
    first = datetime(2026, 9, 15, 21, tzinfo=TZ)
    events = [_event(1, "Arsenal", "Inter Milan", first, "league-phase"),
              _event(2, "Arsenal", "Inter Milan", first + timedelta(days=150), "round-of-16")]
    fixtures = build("cl", today=first.date(), events=events)
    assert len(fixtures) == 2
    assert fixtures[0]["match_id"] == "arsenal_vs_inter_milan_cl"
    assert fixtures[1]["match_id"].startswith("arsenal_vs_inter_milan_cl_2027")


def test_failed_result_fetches_are_not_reported_as_no_new_results(monkeypatch):
    import pytest
    from src import results_update
    def down(league, day):
        raise OSError("ESPN down")
    monkeypatch.setattr(results_update, "_fetch_day", down)
    with pytest.raises(RuntimeError, match="unreachable"):
        results_update.update_club_results(days=2)

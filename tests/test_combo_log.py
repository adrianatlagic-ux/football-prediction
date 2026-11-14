from datetime import datetime, timedelta, timezone

from scripts.grade_combos import settle
from scripts.log_combos import entries_due

NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)


def _ticket(kickoff):
    leg = {"market": "1X2", "outcome": "home_win", "team": "A", "best_odds": 1.5, "home_team": "A",
           "away_team": "B", "commence_time": kickoff.isoformat()}
    return {"leg_count": 2, "combined_odds": 2.25, "conservative_probability": .45, "probability": .5,
            "legs": [leg, {**leg, "team": "C", "home_team": "C", "away_team": "D"}]}


def test_every_ticket_before_its_first_kickoff_is_due_and_started_ones_are_not():
    report = {"days": [{"date": "2026-09-26", "by_size": [{"ticket": _ticket(NOW + timedelta(hours=3))}]}],
              "agree_days": [{"date": "2026-09-26", "by_size": [{"ticket": _ticket(NOW - timedelta(minutes=5))}]}]}
    due = entries_due(report, "soccer_uefa_nations_league", NOW)
    assert [e["policy"] for e in due] == ["market"]


def test_a_new_version_is_logged_only_when_the_legs_change():
    from scripts.log_combos import new_versions
    report = {"days": [{"date": "2026-09-26", "by_size": [{"ticket": _ticket(NOW + timedelta(hours=3))}]}]}
    first = entries_due(report, "nl", NOW)
    assert new_versions(first, []) == first
    # Same legs, other odds: nothing new.
    moved = [{**first[0], "combined_odds": 2.4}]
    assert new_versions(moved, first) == []
    # Another leg: a new version.
    other = [{**first[0], "legs": [first[0]["legs"][0], {**first[0]["legs"][1], "team": "D"}]}]
    assert new_versions(other, first) == other


def test_new_rows_carry_no_quote_basis_and_old_rows_still_get_their_slot():
    from scripts.log_combos import _key
    ticket = _ticket(NOW + timedelta(hours=3))
    row = entries_due({"policy": "ai_pick", "parameters": {"same_bookmaker": False},
                       "days": [{"date": "2026-09-26", "by_size": [{"ticket": ticket}]}]}, "nl", NOW)[0]
    assert "quote_basis" not in row
    assert _key({**row, "quote_basis": "best_singles_mixed_books"}) != _key(row)  # old rows keep their own slot


def test_a_combo_is_lost_on_its_first_losing_leg_even_with_legs_pending():
    t = _ticket(NOW)
    lost = {("a", "b"): {"home_score": 0, "away_score": 1}}
    assert settle(t, lost) == "loss"
    assert settle(t, {("a", "b"): {"home_score": 2, "away_score": 0}}) is None
    both = {("a", "b"): {"home_score": 2, "away_score": 0}, ("c", "d"): {"home_score": 1, "away_score": 0}}
    assert settle(t, both) == "win"


def _report(kickoff, policy="agree"):
    return {"policy": policy, "days": [{"date": "2026-09-26", "by_size": [{"ticket": _ticket(kickoff)}]}]}


def test_a_ticket_is_not_logged_until_the_hour_before_its_first_match():
    from scripts.log_combos import entries_at_prekickoff
    assert entries_at_prekickoff(_report(NOW + timedelta(hours=3)), "nl", NOW, lambda leg: True) == []
    assert entries_at_prekickoff(_report(NOW + timedelta(minutes=61)), "nl", NOW, lambda leg: True) == []


def test_in_the_hour_it_is_logged_once_the_ai_check_of_the_first_match_is_done():
    from scripts.log_combos import entries_at_prekickoff
    report = _report(NOW + timedelta(minutes=50))
    assert entries_at_prekickoff(report, "nl", NOW, lambda leg: False) == []
    seen = []
    due = entries_at_prekickoff(report, "nl", NOW, lambda leg: seen.append(leg["home_team"]) or True)
    assert [e["trigger"] for e in due] == ["ki_check_done"]
    assert seen == ["A"]  # the check is asked about the earliest leg


def test_half_an_hour_before_kickoff_the_ticket_is_logged_even_if_the_check_never_finished():
    from scripts.log_combos import entries_at_prekickoff
    due = entries_at_prekickoff(_report(NOW + timedelta(minutes=25)), "nl", NOW, lambda leg: False)
    assert [e["trigger"] for e in due] == ["last_resort"]
    assert entries_at_prekickoff(_report(NOW - timedelta(minutes=1)), "nl", NOW, lambda leg: True) == []


def test_a_ticket_is_logged_only_once_per_first_kickoff():
    from scripts.log_combos import entries_at_prekickoff, not_yet_logged
    due = entries_at_prekickoff(_report(NOW + timedelta(minutes=40)), "nl", NOW, lambda leg: True)
    first = not_yet_logged(due, [])
    assert first == due
    later = entries_at_prekickoff(_report(NOW + timedelta(minutes=40)), "nl", NOW + timedelta(minutes=10), lambda leg: True)
    assert not_yet_logged(later, first) == []
    # Another rule's ticket of the same day is its own slot.
    other = entries_at_prekickoff(_report(NOW + timedelta(minutes=40), "market"), "nl", NOW, lambda leg: True)
    assert not_yet_logged(other, first) == other

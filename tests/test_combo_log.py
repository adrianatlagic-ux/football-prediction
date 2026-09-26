from datetime import datetime, timedelta, timezone

from scripts.grade_combos import settle
from scripts.log_combos import entries_due

NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)


def _ticket(kickoff):
    leg = {"market": "1X2", "outcome": "home_win", "team": "A", "best_odds": 1.5, "home_team": "A",
           "away_team": "B", "commence_time": kickoff.isoformat()}
    return {"leg_count": 2, "combined_odds": 2.25, "conservative_probability": .45, "probability": .5,
            "legs": [leg, {**leg, "team": "C", "home_team": "C", "away_team": "D"}]}


def test_both_rules_are_logged_only_in_the_hour_before_kickoff():
    report = {"days": [{"date": "2026-09-26", "by_size": [{"ticket": _ticket(NOW + timedelta(minutes=45))}]}],
              "legacy_v3_days": [{"date": "2026-09-26", "by_size": [{"ticket": _ticket(NOW + timedelta(hours=3))}]}]}
    due = entries_due(report, "soccer_uefa_nations_league", NOW)
    assert [e["policy"] for e in due] == ["market"]


def test_a_combo_is_lost_on_its_first_losing_leg_even_with_legs_pending():
    t = _ticket(NOW)
    lost = {("a", "b"): {"home_score": 0, "away_score": 1}}
    assert settle(t, lost) == "loss"
    assert settle(t, {("a", "b"): {"home_score": 2, "away_score": 0}}) is None
    both = {("a", "b"): {"home_score": 2, "away_score": 0}, ("c", "d"): {"home_score": 1, "away_score": 0}}
    assert settle(t, both) == "win"

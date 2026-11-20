"""Lenny Zero bot: the story only ever moves on real GoalIQ tips and results."""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

_path = Path(__file__).resolve().parents[1] / "social" / "lenny" / "lenny.py"
_spec = importlib.util.spec_from_file_location("lenny", _path)
lenny = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lenny)

TZ = lenny.TZ
CONFIG = {"start_bankroll_eur": 50.0, "stake_fraction": 0.5, "min_stake_eur": 5.0, "comeback_refill_eur": 50.0,
          "preview_horizon_days": 4, "max_episodes_per_week": 3,
          "featured_clubs": ["Bayern Munich", "FC Bayern München"]}


def _fx(mid, home, away, kickoff, group="Spieltag 10"):
    return {"match_id": mid, "home_team": home, "away_team": away, "competition": "bl", "group": group,
            "kickoff": kickoff}


FIXTURES = [
    _fx("a_b", "Team A", "Team B", datetime(2026, 11, 21, 15, 30, tzinfo=TZ)),
    _fx("bay_c", "Bayern Munich", "Team C", datetime(2026, 11, 22, 17, 30, tzinfo=TZ)),
    _fx("d_e", "Team D", "Team E", datetime(2026, 11, 28, 15, 30, tzinfo=TZ), group="Spieltag 11"),
]


def _tip(home, away, kickoff_utc, status="ok", result=(2, 1), market="1X2", outcome="home_win", team=None,
         odds=1.8):
    entry = {"home_team": home, "away_team": away, "commence_time": kickoff_utc,
             "bet_tip": {"status": status,
                         "tip": {"market": market, "outcome": outcome, "team": team or home, "best_odds": odds}
                         if status == "ok" else None}}
    if result:
        entry["result"] = {"home_score": result[0], "away_score": result[1]}
    return entry


BAYERN = "2026-11-22T16:30:00Z"
EARLY = "2026-11-21T14:30:00Z"
AFTER = datetime(2026, 11, 23, 10, 0, tzinfo=TZ)


def _opened(**changes):
    """State after the two fixed opening episodes (pilot, discovery)."""
    state = lenny.fresh_state(CONFIG)
    for _ in range(2):
        state = lenny.commit(state, lenny.next_brief(state, CONFIG, FIXTURES, [], datetime(2026, 11, 1, tzinfo=TZ)))
    return state | changes


def _after_preview():
    state = _opened()
    preview = lenny.next_brief(state, CONFIG, FIXTURES, [], datetime(2026, 11, 20, 9, 0, tzinfo=TZ))
    return lenny.commit(state, preview), preview


def test_the_story_opens_at_rock_bottom_then_finds_the_app():
    state = lenny.fresh_state(CONFIG)
    pilot = lenny.next_brief(state, CONFIG, FIXTURES, [], datetime(2026, 11, 20, 9, 0, tzinfo=TZ))
    assert pilot["type"] == "pilot" and pilot["bankroll_after_eur"] == 3.12
    state = lenny.commit(state, pilot)
    discovery = lenny.next_brief(state, CONFIG, FIXTURES, [], datetime(2026, 11, 20, 9, 0, tzinfo=TZ))
    assert discovery["type"] == "discovery" and discovery["bankroll_after_eur"] == 50.0


def test_preview_announces_the_next_matchday_without_naming_a_tip():
    state, preview = _after_preview()
    assert preview["type"] == "preview"
    assert preview["matchday"]["label"] == "Bundesliga Spieltag 10"
    assert preview["big_games"][0]["home_team"] == "Bayern Munich"
    assert preview["stake_eur"] == 25.0
    assert "tip" not in preview and state["open_bet"]["id"] == preview["matchday"]["id"]


def test_nothing_happens_while_the_matchday_runs():
    state, _ = _after_preview()
    brief = lenny.next_brief(state, CONFIG, FIXTURES, [], datetime(2026, 11, 22, 12, 0, tzinfo=TZ))
    assert brief["type"] == "none"


def test_lenny_follows_the_featured_club_tip_and_wins_at_the_real_odds():
    state, _ = _after_preview()
    tips = [_tip("Team A", "Team B", EARLY, result=(0, 3)), _tip("FC Bayern München", "Team C", BAYERN)]
    brief = lenny.next_brief(state, CONFIG, FIXTURES, tips, AFTER)
    assert brief["type"] == "result" and brief["match"]["home_team"] == "FC Bayern München"
    assert brief["outcome"] == "win" and brief["profit_eur"] == 20.0 and brief["bankroll_after_eur"] == 70.0
    after = lenny.commit(state, brief)
    assert after["open_bet"] is None and after["bankroll_eur"] == 70.0


def test_without_a_featured_tip_the_first_published_tip_counts_even_if_it_lost():
    state, _ = _after_preview()
    tips = [_tip("Team A", "Team B", EARLY, result=(0, 3)),
            _tip("FC Bayern München", "Team C", BAYERN, status="no_agreement")]
    brief = lenny.next_brief(state, CONFIG, FIXTURES, tips, AFTER)
    assert brief["match"]["home_team"] == "Team A"
    assert brief["outcome"] == "loss" and brief["bankroll_after_eur"] == 25.0 and brief["mood_after"] == "shaken"


def test_a_matchday_without_any_tip_closes_as_skip_after_a_few_days():
    state, _ = _after_preview()
    tips = [_tip("Team A", "Team B", EARLY, status="ai_unsure")]
    assert lenny.next_brief(state, CONFIG, FIXTURES, tips, AFTER)["type"] == "none"
    later = lenny.next_brief(state, CONFIG, FIXTURES, tips, datetime(2026, 11, 26, 10, 0, tzinfo=TZ))
    assert later["type"] == "skip" and later["bankroll_after_eur"] == 50.0


def test_an_unsettled_tip_waits_for_the_log_sync():
    state, _ = _after_preview()
    tips = [_tip("FC Bayern München", "Team C", BAYERN, result=None)]
    assert lenny.next_brief(state, CONFIG, FIXTURES, tips, AFTER)["type"] == "none"


def test_broke_lenny_gets_a_comeback_episode():
    state = _opened(bankroll_eur=3.12)
    brief = lenny.next_brief(state, CONFIG, FIXTURES, [], datetime(2026, 11, 20, 9, 0, tzinfo=TZ))
    assert brief["type"] == "broke" and brief["bankroll_after_eur"] == 53.12


def test_weekly_cap_stops_production():
    state = _opened()
    now = datetime(2026, 11, 20, 9, 0, tzinfo=TZ)
    state["episodes"] = [{"episode": i, "type": "preview", "created_at": now.isoformat()} for i in range(3)]
    assert lenny.next_brief(state, CONFIG, FIXTURES, [], now)["type"] == "none"


def test_at_most_one_life_episode_a_week_when_no_matchday_is_ahead():
    state = _opened()
    now = datetime(2026, 12, 20, 9, 0, tzinfo=TZ)
    first = lenny.next_brief(state, CONFIG, FIXTURES, [], now)
    assert first["type"] == "lifestyle"
    state = lenny.commit(state, first)
    assert lenny.next_brief(state, CONFIG, FIXTURES, [], now)["type"] == "none"


def test_commit_refuses_out_of_order_or_empty_briefs():
    state = lenny.fresh_state(CONFIG)
    with pytest.raises(SystemExit):
        lenny.commit(state, {"episode": 5, "type": "lifestyle"})
    with pytest.raises(SystemExit):
        lenny.commit(state, {"episode": 1, "type": "none"})


@pytest.mark.parametrize("market,outcome,team,text", [
    ("Handicap +0.5", "handicap", "Köln", "Köln not to lose"),
    ("Handicap +1.5", "handicap", "Union", "Union not to lose by 2 or more"),
    ("Handicap -1.5", "handicap", "Arsenal", "Arsenal to win by 2 or more"),
    ("Over/Under 2.5", "Over", None, "over 2.5 goals"),
    ("BTTS", "Yes", None, "both teams to score"),
])
def test_tips_read_as_plain_english(market, outcome, team, text):
    assert lenny.describe_tip({"market": market, "outcome": outcome, "team": team}, "H", "A") == text

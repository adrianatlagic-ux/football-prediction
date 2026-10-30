"""Regression tests for the background refresh paths that serve live picks."""
from datetime import datetime, timedelta, timezone
import pytest


@pytest.mark.parametrize("stage,fetched,expected", [
    ("daily", "2026-10-29T13:35:00Z", False),
    ("initial", "2026-10-30T04:30:00Z", False),
    ("daily", "2026-10-30T04:30:00Z", False),
    ("daily", "2026-10-30T06:08:00Z", True),
    ("daily", "2026-10-30T10:00:00Z", False),
    ("final", "2026-10-30T06:08:00Z", False),
    ("daily", None, False),
])
def test_first_ai_call_needs_todays_morning_snapshot(stage, fetched, expected):
    from src.ai_tip_research import morning_snapshot_ready
    now = datetime(2026, 10, 30, 9, tzinfo=timezone.utc)
    assert morning_snapshot_ready({"odds_stage": stage, "odds_fetched_at": fetched}, now) is expected


def test_first_ai_call_waits_for_supplementary_book_and_retry(monkeypatch):
    from src import book_odds
    sport = "soccer_germany_bundesliga"
    monkeypatch.setenv("APIFY_TOKEN", "test-only")
    monkeypatch.setattr(book_odds, "_morning_retry", {})
    monkeypatch.setattr(book_odds, "REFRESH_LOG", {})
    snapshot = "2026-10-30T06:08:00Z"
    assert not book_odds.morning_read_finished(sport, snapshot)
    book_odds.REFRESH_LOG[sport] = {"kind": "morning", "at": "2026-10-29T06:09:00Z"}
    assert not book_odds.morning_read_finished(sport, snapshot)
    book_odds.REFRESH_LOG[sport]["at"] = "2026-10-30T06:09:00Z"
    assert book_odds.morning_read_finished(sport, snapshot)
    book_odds._morning_retry[sport] = {"next_at": None}
    assert not book_odds.morning_read_finished(sport, snapshot)
    monkeypatch.delenv("APIFY_TOKEN")
    assert book_odds.morning_read_finished(sport, snapshot)


@pytest.mark.parametrize("morning_ready,book_ready", [(True, True), (False, True), (True, False)])
def test_agent_refresh_uses_cached_prediction_snapshot(monkeypatch, morning_ready, book_ready):
    from api import app as api
    from src import ai_tip_research
    monkeypatch.setattr(ai_tip_research, "morning_snapshot_ready", lambda vb: morning_ready)
    monkeypatch.setattr(api.book_odds, "morning_read_finished", lambda *args: book_ready)

    match = {"home_team": "Alpha", "away_team": "Bravo"}
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    result = {**match, "odds_found": True, "in_play": False,
              "commence_time": kickoff, "sport_key": "soccer_test", "event_id": "event-1",
              "odds_fetched_at": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr(api, "_get_prediction_index", lambda: {("alpha", "bravo"): match})
    monkeypatch.setattr(api, "_compute_value_bets", lambda *args: result)
    monkeypatch.setattr(api, "_call_gemini_agent_pick", lambda *args: {"pick": {"market": "1X2"}})
    monkeypatch.setattr(api.time, "monotonic", lambda: 999.0)

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            self.target()

    class ImmediatePool:
        def __init__(self, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def map(self, func, values):
            return map(func, values)

    monkeypatch.setattr(api.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(api, "ThreadPoolExecutor", ImmediatePool)
    api._agent_picks_cache = {}
    api._agent_picks_refresh_in_progress = False
    api._agent_picks_last_check = 0
    api._refresh_agent_picks([])

    if morning_ready and book_ready:
        assert api._agent_picks_cache[api._agent_key(result)]["pick"]["market"] == "1X2"
    else:
        assert not api._agent_picks_cache
    assert not api._agent_picks_refresh_in_progress


def test_best_bets_reads_the_pre_kickoff_cache(monkeypatch):
    from api import app as api

    match = {"home_team": "Alpha", "away_team": "Bravo"}
    refreshed = {**match, "odds_found": True, "in_play": False,
                 "odds_refreshed": True, "recommendation": {"market": "1X2"}}
    monkeypatch.setattr(api, "_get_odds", lambda: [])
    monkeypatch.setattr(api, "_get_prediction_index", lambda: {("alpha", "bravo"): match})
    monkeypatch.setattr(api, "_refresh_agent_picks", lambda odds: None)
    monkeypatch.setattr(api, "_maybe_prekickoff_refresh", lambda odds: None)
    monkeypatch.setattr(api, "_get_agent_pick", lambda vb: None)
    monkeypatch.setattr(api, "_combine_recommendation", lambda vb, agent: {"consensus_pick": {"market": "1X2"}})
    monkeypatch.setattr(api, "_compute_value_bets", lambda *args: {"odds_found": False})
    api._prekickoff_vb_cache = {api._match_key("Alpha", "Bravo"): refreshed}

    response = api.best_bets()
    assert response["best_bets"][0]["odds_refreshed"] is True


def test_agent_refresh_does_not_ask_gemini_again_for_a_cached_match(monkeypatch):
    """A match with an agent pick is never sent to Gemini again by the
    matchday pass. The pass runs every few minutes; a skip check on a
    different key than the one the pick is stored under re-researched every
    match on every pass."""
    from api import app as api
    from src import ai_tip_research
    monkeypatch.setattr(ai_tip_research, "morning_snapshot_ready", lambda vb: True)

    match = {"home_team": "Alpha", "away_team": "Bravo"}
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    result = {**match, "odds_found": True, "in_play": False,
              "commence_time": kickoff, "sport_key": "soccer_test", "event_id": "event-1",
              "odds_fetched_at": datetime.now(timezone.utc).isoformat()}
    calls = []

    monkeypatch.setattr(api, "_get_prediction_index", lambda: {("alpha", "bravo"): match})
    monkeypatch.setattr(api, "_compute_value_bets", lambda *args: result)
    monkeypatch.setattr(api, "_call_gemini_agent_pick",
                        lambda *args, **kwargs: calls.append(args) or {"pick": {"market": "1X2"}})

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            self.target()

    class ImmediatePool:
        def __init__(self, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def map(self, func, values):
            return map(func, values)

    monkeypatch.setattr(api.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(api, "ThreadPoolExecutor", ImmediatePool)
    api._agent_picks_cache = {}
    api._agent_picks_refresh_in_progress = False
    for clock in (1000.0, 2000.0, 3000.0):
        monkeypatch.setattr(api.time, "monotonic", lambda clock=clock: clock)
        api._agent_picks_last_check = 0
        api._refresh_agent_picks([])

    assert len(calls) == 1


def test_a_failed_gemini_call_is_retried_only_after_two_hours(monkeypatch):
    """An unreadable answer is still a billed call; asking again on every
    pass would pay for it every few minutes."""
    from api import app as api
    from src import ai_tip_research
    monkeypatch.setattr(ai_tip_research, "morning_snapshot_ready", lambda vb: True)

    match = {"home_team": "Alpha", "away_team": "Bravo"}
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    result = {**match, "odds_found": True, "in_play": False,
              "commence_time": kickoff, "sport_key": "soccer_test", "event_id": "event-2",
              "odds_fetched_at": datetime.now(timezone.utc).isoformat()}
    calls = []
    monkeypatch.setattr(api, "_get_prediction_index", lambda: {("alpha", "bravo"): match})
    monkeypatch.setattr(api, "_compute_value_bets", lambda *args: result)
    monkeypatch.setattr(api, "_call_gemini_agent_pick", lambda *args, **kwargs: calls.append(args) or None)

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            self.target()

    class ImmediatePool:
        def __init__(self, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def map(self, func, values):
            return map(func, values)

    monkeypatch.setattr(api.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(api, "ThreadPoolExecutor", ImmediatePool)
    api._agent_picks_cache = {}
    api._agent_failed_at = {}
    api._agent_picks_refresh_in_progress = False
    wall = [10_000.0]
    monkeypatch.setattr(api.time, "time", lambda: wall[0])
    for clock, now in ((1000.0, 10_000.0), (2000.0, 10_600.0), (3000.0, 10_000.0 + 2 * 3600 + 1)):
        wall[0] = now
        monkeypatch.setattr(api.time, "monotonic", lambda clock=clock: clock)
        api._agent_picks_last_check = 0
        api._refresh_agent_picks([])

    assert len(calls) == 2      # first pass, then again only after two hours


def test_agent_picks_survive_a_restart(monkeypatch):
    """Kept on disk: a deploy must not send every match to Gemini again."""
    from api import app as api

    kickoff = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    key = ("soccer_test", "event-3", kickoff, "alpha", "bravo")
    stale = ("soccer_test", "event-0", old, "x", "y")
    monkeypatch.setattr(api, "_agent_picks_cache", {key: {"pick": {"market": "1X2"}}, stale: {"pick": None}})
    monkeypatch.setattr(api, "_agent_prekickoff_done", {key})
    api._save_agent_cache()

    monkeypatch.setattr(api, "_agent_picks_cache", {})
    monkeypatch.setattr(api, "_agent_prekickoff_done", set())
    api._load_agent_cache()
    assert api._agent_picks_cache == {key: {"pick": {"market": "1X2"}}}   # the finished match is dropped
    assert api._agent_prekickoff_done == {key}


def test_the_old_bet_tip_needs_model_and_ai_and_takes_the_better_price_of_one_bet():
    from api import app as api
    win = {"market": "1X2", "outcome": "win", "team": "Portugal", "best_odds": 1.65,
           "market_probability": .58, "model_probability_raw": .60, "probability": .59}
    minus = {"market": "Handicap -0.5", "outcome": "handicap", "team": "Portugal", "best_odds": 1.55,
             "market_probability": .59, "model_probability_raw": .60, "probability": .59}
    under = {"market": "Over/Under 4.5", "outcome": "Under", "team": None, "best_odds": 1.33,
             "market_probability": .70, "model_probability_raw": .70, "probability": .70}
    vb = {"home_team": "Portugal", "away_team": "Norway", "bets": [win, minus, under]}
    tip = api._bet_tip_v1(vb, {"pick": win})
    assert tip["status"] == "ok" and tip["tip"] is win          # the same bet at 1.65, not 1.55
    assert api._bet_tip_v1(vb, None)["status"] == "waiting_for_ai"
    # The model 8 points below the market: no agreement, no tip.
    doubt = {**win, "model_probability_raw": .50}
    assert api._bet_tip_v1({**vb, "bets": [doubt]}, {"pick": doubt})["status"] == "no_agreement"


def test_the_bet_tip_is_the_ai_pick_checked_by_the_model_and_withheld_when_the_ai_wavers():
    from api import app as api
    pick = {"market": "Over/Under 2.5", "outcome": "Under", "team": None, "best_odds": 1.72,
            "market_probability": .55, "model_probability_raw": .61, "probability": .60}
    vb = {"home_team": "A", "away_team": "B", "bets": [pick]}
    assert api._bet_tip(vb, None)["status"] == "waiting_for_ai"
    first = api._bet_tip(vb, {"pick": pick, "revised_from_previous": None})
    assert first["status"] == "ok" and first["tip"] is pick and first["confirmed"] is False   # provisional
    kept = api._bet_tip(vb, {"pick": pick, "revised_from_previous": False})
    assert kept["confirmed"] is True
    changed = api._bet_tip(vb, {"pick": pick, "revised_from_previous": True})
    assert changed["status"] == "ai_unsure" and changed["tip"] is None and changed["withheld"] is pick
    below = {**pick, "model_probability_raw": .54}
    assert api._bet_tip(vb, {"pick": below})["status"] == "no_agreement"


def test_the_ki_combo_takes_only_the_ai_picks_the_model_backs():
    from src.combo_ticket import leg_pool
    def bet(team, odds, market_p, model_p, market="1X2"):
        return {"market": market, "outcome": "home_win" if market == "1X2" else "Under",
                "team": team if market == "1X2" else None, "best_odds": odds, "bookmaker": "bet-at-home",
                "bookmaker_key": "betathome", "probability": model_p, "market_probability": market_p,
                "model_probability_raw": model_p, "quote_fresh": True}
    def vb(home, away, pick, extra, revised=False):
        return ({}, {"odds_found": True, "snapshot_valid": True, "home_team": home, "away_team": away,
                     "commence_time": "2026-10-13T18:45:00Z", "sport_key": "soccer_uefa_champs_league",
                     "bets": [pick, extra], "agent_pick": pick, "agent_revised": revised})
    pairs = [vb("A", "B", bet("A", 1.8, .55, .60), bet("A", 1.4, .70, .72, "Over/Under 3.5")),       # pick backed: in
             vb("C", "D", bet("C", 1.9, .52, .49), bet("C", 1.4, .70, .72, "Over/Under 3.5")),       # model below: out
             vb("E", "F", bet("E", 1.7, .58, .62), bet("E", 1.4, .70, .72, "Over/Under 3.5"), revised=True)]  # wavered: out
    legs = leg_pool(pairs, book="betathome", policy="ki")
    assert [(l["home_team"], l["best_odds"]) for l in legs] == [("A", 1.8)]


def test_every_change_withholds_the_tip_and_logs_whether_it_kept_the_side():
    from api import app as api
    win = {"market": "1X2", "outcome": "home_win", "team": "Leipzig"}
    minus = {"market": "Handicap -1.5", "outcome": "handicap", "team": "Leipzig", "best_odds": 2.4,
             "market_probability": .45, "model_probability_raw": .50}
    plus = {**minus, "market": "Handicap +1.5"}
    other = {**minus, "team": "Frankfurt"}
    over = {"market": "Over/Under 2.5", "outcome": "Over", "team": None}
    vb = {"home_team": "Leipzig", "away_team": "Frankfurt"}
    for pick, change in ((minus, "same_side"), (plus, "same_side"), (other, "changed_mind"), (over, "changed_mind")):
        tip = api._bet_tip(vb, {"pick": pick, "first_pick": win, "revised_from_previous": True})
        assert tip["status"] == "ai_unsure" and tip["tip"] is None
        assert tip["change"] == change and tip["first_pick"] == win
    over15 = {**over, "market": "Over/Under 1.5"}
    assert api._bet_tip(vb, {"pick": over15, "first_pick": over, "revised_from_previous": True})["change"] == "same_side"
    assert api._bet_tip(vb, {"pick": minus, "revised_from_previous": True})["change"] == "unknown"

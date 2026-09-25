"""Regression tests for the background refresh paths that serve live picks."""
from datetime import datetime, timedelta, timezone


def test_agent_refresh_uses_cached_prediction_snapshot(monkeypatch):
    from api import app as api

    match = {"home_team": "Alpha", "away_team": "Bravo"}
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    result = {**match, "odds_found": True, "in_play": False,
              "commence_time": kickoff, "sport_key": "soccer_test", "event_id": "event-1"}

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

    assert api._agent_picks_cache[api._agent_key(result)]["pick"]["market"] == "1X2"
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

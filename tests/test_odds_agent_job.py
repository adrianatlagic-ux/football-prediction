"""The manual odds-and-agent job (.github/workflows/odds_agent.yml)."""
from datetime import datetime, timedelta, timezone


def test_job_reads_odds_then_book_then_agent(monkeypatch, tmp_path):
    from src import jobs
    monkeypatch.setattr(jobs, "REPORTS", tmp_path)
    calls = []

    def odds(force=False, book_in_background=True):
        calls.append(("odds", force, book_in_background))
        return [{"id": "x"}]

    report = jobs.run_odds_and_agent(
        odds, lambda events: calls.append(("book", len(events))) or {"soccer_test": True},
        lambda events, hours, force: calls.append(("agent", hours, force)) or {"picked": 1},
        agent_hours=24, force_agent=True)

    assert calls == [("odds", True, False), ("book", 1), ("odds", False, True), ("agent", 24, True)]
    assert report["errors"] == [] and report["agent"] == {"picked": 1}
    assert (tmp_path / "last_odds_agent.json").exists()


def test_failed_forced_read_falls_back_to_cached_odds(monkeypatch, tmp_path):
    from src import jobs
    monkeypatch.setattr(jobs, "REPORTS", tmp_path)

    def odds(force=False, book_in_background=True):
        if force:
            raise RuntimeError("quota")
        return [{"id": "x"}]

    report = jobs.run_odds_and_agent(odds, lambda e: {}, lambda e, h, f: {"picked": 2}, agent_hours=48)
    assert report["odds_events_cached"] == 1 and report["agent"] == {"picked": 2}
    assert report["errors"] and report["errors"][0].startswith("odds:")


def _immediate_pool(monkeypatch, api):
    class ImmediatePool:
        def __init__(self, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def map(self, func, values):
            return map(func, values)
    monkeypatch.setattr(api, "ThreadPoolExecutor", ImmediatePool)
    monkeypatch.setattr(api, "_save_agent_cache", lambda: None)


def test_agent_window_and_force(monkeypatch):
    from api import app as api
    _immediate_pool(monkeypatch, api)
    match = {"home_team": "Alpha", "away_team": "Bravo"}
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat()
    result = {**match, "odds_found": True, "in_play": False,
              "commence_time": kickoff, "sport_key": "soccer_test", "event_id": "event-1"}
    seen = []
    monkeypatch.setattr(api, "_compute_value_bets", lambda *args: result)
    monkeypatch.setattr(api, "_call_gemini_agent_pick",
                        lambda *args, previous_eval=None: seen.append(previous_eval) or {"pick": {"market": "1X2"}})
    api._agent_picks_cache = {}
    api._agent_failed_at = {}

    # 30 hours out: outside the default 12-hour window, inside 48.
    assert api._evaluate_agent_picks([], [match]) == {"outside_window": 1}
    assert api._evaluate_agent_picks([], [match], window_hours=48) == {"picked": 1}
    assert api._evaluate_agent_picks([], [match], window_hours=48) == {"already_picked": 1}
    assert api._evaluate_agent_picks([], [match], window_hours=48, force=True) == {"picked": 1}
    assert seen == [None, {"pick": {"market": "1X2"}}]


def test_endpoint_requires_the_job_token(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from api import app as api
    monkeypatch.setattr(api, "PREDICTIONS_WRITE_TOKEN", "secret")
    with pytest.raises(HTTPException) as err:
        api.job_odds_agent(agent_hours=48, force_agent=False, x_prediction_token="wrong")
    assert err.value.status_code == 401

from datetime import datetime, timedelta, timezone

import scripts.refresh_squad_predictions as rsp
import src.jobs as jobs
import src.lineups as lineups
import src.squad_data as squad_data


def test_a_match_with_only_one_valued_eleven_is_retried_not_adjusted(monkeypatch):
    kickoff = datetime.now(timezone.utc) + timedelta(minutes=50)
    fixture = {"match_id": "a_vs_b_nl", "home_team": "A", "away_team": "B",
               "competition": "nations_league", "kickoff": kickoff}
    written = []
    monkeypatch.setattr(rsp, "upcoming", lambda minutes, now: [fixture])
    monkeypatch.setattr(rsp, "load_registry", lambda comp: {"A": 1, "B": 2})
    monkeypatch.setattr(squad_data, "cached_squads", lambda ids, ttl: {"1": [], "2": []})
    monkeypatch.setattr(lineups, "fetch_starters", lambda *a: {"home": ["x"] * 11, "away": ["y"] * 11, "bench": {}})
    # Home valued, away not (e.g. names not found in the squad).
    monkeypatch.setattr(lineups, "lineup_share",
                        lambda starters, squad, bench=None: {"share": 0.5} if starters[0] == "x" else None)
    monkeypatch.setattr(jobs, "_cached", lambda match_id: {})
    monkeypatch.setattr(jobs, "_write", lambda f, result: written.append(result))
    monkeypatch.setattr(jobs, "_report", lambda name, report: report)

    class Predictor:
        def predict_match(self, *a, **k):
            raise AssertionError("no prediction without both elevens")

    report = jobs.run_hourly(Predictor, Predictor)
    assert written == []
    assert report["waiting_for_lineup"] == ["a_vs_b_nl (not valued: away)"]

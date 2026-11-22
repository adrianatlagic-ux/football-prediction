from datetime import datetime, timezone

from src import fixtures, jobs


def test_the_daily_job_predicts_every_match_up_to_three_days_ahead(monkeypatch):
    # Sunday 22 November, 07:05 Berlin (06:05 UTC); the page opens a Tuesday match's analysis at
    # Sunday 00:00, a Wednesday match's on Monday 00:00 - so the Sunday job must reach Wednesday.
    now = datetime(2026, 11, 22, 6, 5, tzinfo=timezone.utc)
    day = lambda d, t="18:45": {"match_id": f"m{d}{t}", "date": f"2026-11-{d}", "time": t, "home_team": "A", "away_team": "B"}
    monkeypatch.setattr(fixtures, "load_all", lambda: {"cl": [
        day(22, "05:00"),                     # already played this morning
        day(22, "20:00"), day(24), day(25, "23:30"),   # today, Tuesday, Wednesday night
        day(26, "00:30"),                      # Thursday: not yet
    ]})
    ids = [f["match_id"] for f in jobs.predict_due(now)]
    assert ids == ["m2220:00", "m2418:45", "m2523:30"]


def test_the_evening_run_takes_in_results_and_predicts_again_without_odds(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src import results_update, scheduler
    monkeypatch.setattr(jobs, "REPORTS", tmp_path)
    monkeypatch.setattr(results_update, "update_club_results", lambda: [1, 2])
    monkeypatch.setattr(results_update, "update_national_results", lambda: [])
    monkeypatch.setattr(fixtures, "write_all", lambda: {})
    due = [{"match_id": "m1", "competition": "champions_league"}, {"match_id": "m2", "competition": "nations_league"}]
    monkeypatch.setattr(jobs, "predict_due", lambda now: due)
    done = []
    monkeypatch.setattr(jobs, "repredict", lambda fixture, predictor, now: done.append((fixture["match_id"], predictor)))
    club = lambda: SimpleNamespace(refresh_history=lambda: 3, name="club")
    national = lambda: SimpleNamespace(refresh_history=lambda: 0, name="national")
    report = jobs.run_evening(club, national)
    assert report["club_results"] == 2 and report["club_history_added"] == 3
    assert report["predicted"] == ["m1", "m2"] and not report["errors"]
    assert [(m, p.name) for m, p in done] == [("m1", "club"), ("m2", "national")]
    assert "morning_odds" not in report
    # once per day: the scheduler reads the finished report
    monkeypatch.setattr("src.jobs.REPORTS", tmp_path)
    assert scheduler._evening_done_today(datetime.fromisoformat(report["finished_at"]))
    assert not scheduler._evening_done_today(datetime(2000, 1, 1, tzinfo=timezone.utc))

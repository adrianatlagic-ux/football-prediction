"""The scheduled work the server does on its own, started by GitHub's clock.

GitHub Actions only knocks (api/jobs.yml calls POST /jobs/daily and
/jobs/hourly); the server does the work, because it already holds both
models - GitHub would need them downloaded first, and there is nowhere
they could be downloaded from.

daily  (06:05 UTC) - append yesterday's results, let both models re-read
                     their history, re-predict every match of the next 48
                     hours, and take the morning odds read.
hourly (xx:15)     - squad values for matches kicking off within 75 minutes,
                     once per match (the old GitHub job ran every quarter
                     hour and needed the models on GitHub's side).

Neither retrains a model: a monthly refit measured no better than a frozen
one (data/model_reports/retraining_v3). Retraining stays a manual step.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "predictions_cache"
REPORTS = ROOT / "data" / "jobs"
REPREDICT_HOURS = 48
SQUAD_WINDOW_MINUTES = 75

_lock = threading.Lock()


def _report(name: str, report: dict) -> dict:
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"last_{name}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
    return report


def _cached(match_id: str) -> dict:
    try:
        return json.loads((CACHE / f"{match_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(fixture: dict, result: dict) -> None:
    for key in ("match_id", "group", "date", "time"):
        result.setdefault(key, fixture.get(key))
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{fixture['match_id']}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def repredict(fixture: dict, predictor, now: datetime) -> dict:
    """One fixture from the refreshed history. The AI scenario sentence is
    kept from the earlier prediction when there is one - it describes the
    match, not the decimals, and regenerating it daily would only cost."""
    national = fixture["competition"] == "nations_league"
    result = (predictor.predict_match(fixture["home_team"], fixture["away_team"], is_knockout=False)
              if national else predictor.predict_match(fixture["home_team"], fixture["away_team"]))
    previous = _cached(fixture["match_id"])
    from src.poisson_model import SCENARIO_LANG
    previous_markets = (previous.get("score_prediction") or {}).get("betting_markets") or {}
    scenario = previous_markets.get("scenario")
    # The written scenario describes the predicted winner; once the winner
    # changes it has to be written again. So is one in another language.
    if previous.get("prediction") and previous.get("prediction") != result.get("prediction"):
        scenario = None
    if previous_markets.get("scenario_lang") != SCENARIO_LANG:
        scenario = None
    if not scenario:
        try:
            from src.scenario_agent import generate_ai_scenario
            scenario = generate_ai_scenario(result, fixture["home_team"], fixture["away_team"], is_knockout=False)
        except Exception:
            scenario = None
    if scenario:
        result.setdefault("score_prediction", {}).setdefault("betting_markets", {})["scenario"] = scenario
    result["history_refreshed_at"] = now.isoformat()
    _write(fixture, result)
    return result


def run_daily(club: Callable, national: Callable, morning_odds: Callable,
              real_results: Optional[Callable] = None) -> dict:
    """Results, history, predictions for the next 48 hours, morning odds and
    the model's track record."""
    from scripts.refresh_squad_predictions import upcoming
    from src.results_update import update_club_results, update_national_results
    now = datetime.now(timezone.utc)
    report = {"started_at": now.isoformat(), "errors": []}
    with _lock:
        _report("daily", {**report, "running": True})
        for label, step in (("club_results", update_club_results), ("national_results", update_national_results)):
            try:
                report[label] = len(step())
            except Exception as exc:
                report["errors"].append(f"{label}: {type(exc).__name__}: {exc}")
        try:
            from src.fixtures import write_all
            report["fixtures"] = write_all()
        except Exception as exc:
            report["errors"].append(f"fixtures: {type(exc).__name__}: {exc}")
        for label, getter in (("club_history_added", club), ("national_history_added", national)):
            try:
                report[label] = getter().refresh_history()
            except Exception as exc:
                report["errors"].append(f"{label}: {type(exc).__name__}: {exc}")
        predicted = []
        for fixture in upcoming(REPREDICT_HOURS * 60, now):
            try:
                predictor = national() if fixture["competition"] == "nations_league" else club()
                repredict(fixture, predictor, now)
                predicted.append(fixture["match_id"])
            except Exception as exc:
                report["errors"].append(f"{fixture['match_id']}: {type(exc).__name__}: {exc}")
        report["predicted"] = predicted
        try:
            morning_odds()
            report["morning_odds"] = True
        except Exception as exc:
            report["errors"].append(f"morning_odds: {type(exc).__name__}: {exc}")
        if real_results is not None:
            # Graded here, on the server's own logs, so the page shows today's
            # record and not the one baked into the last deploy.
            try:
                from scripts.build_model_track_record import refresh
                report["track_record_live"] = sum(b["n"] for b in refresh(real_results())["live"])
            except Exception as exc:
                report["errors"].append(f"track_record: {type(exc).__name__}: {exc}")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return _report("daily", report)


def _lineup_done(fixture: dict) -> bool:
    return bool(_cached(fixture["match_id"]).get("lineup_refreshed_at"))


def run_hourly(club: Callable, national: Callable) -> dict:
    """Line-up strength for matches kicking off within 75 minutes.

    ESPN lists the starters about an hour before kickoff; until it does, the
    match is simply tried again on the next tick. Once both elevens are
    known, each is valued against its squad's best eleven (src/lineups.py)
    and the prediction is moved accordingly - once per match. The squads come
    from Apify, cached a week, so this costs nothing per match.
    """
    from scripts.refresh_squad_predictions import load_registry, upcoming
    from src import lineups
    from src.squad_data import CLUB_SQUAD_TTL, NATIONAL_SQUAD_TTL, cached_squads
    now = datetime.now(timezone.utc)
    report = {"started_at": now.isoformat(), "errors": [], "refreshed": [], "waiting_for_lineup": []}
    with _lock:
        _report("hourly", {**report, "running": True})
        keys = ("probability_home_win", "probability_draw", "probability_away_win")
        for f in upcoming(SQUAD_WINDOW_MINUTES, now):
            if _lineup_done(f):
                continue
            home, away, comp = f["home_team"], f["away_team"], f["competition"]
            try:
                starters = lineups.fetch_starters(comp, home, away, f["kickoff"])
            except Exception as exc:
                report["errors"].append(f"{f['match_id']} line-up: {type(exc).__name__}: {exc}")
                continue
            if not starters:
                report["waiting_for_lineup"].append(f["match_id"])
                continue
            registry = load_registry(comp)
            ids = [registry.get(home), registry.get(away)]
            try:
                ttl = NATIONAL_SQUAD_TTL if comp == "nations_league" else CLUB_SQUAD_TTL
                squads = cached_squads([i for i in ids if i], ttl)
            except Exception as exc:
                report["errors"].append(f"{f['match_id']} squads: {type(exc).__name__}: {exc}")
                continue
            shares = {}
            for side, team_id in (("home", ids[0]), ("away", ids[1])):
                info = (lineups.lineup_share(starters[side], squads.get(str(team_id), []),
                                             starters.get("bench", {}).get(side)) if team_id else None)
                shares[side] = info
            if not shares["home"] or not shares["away"]:
                # Both elevens or neither: counting an unvalued side as full
                # strength would move the prediction toward it. The match stays
                # unmarked, so every tick until kickoff tries again; if one side
                # never gets valued, the prediction stays as it was.
                missing = [s for s in ("home", "away") if not shares[s]]
                report["waiting_for_lineup"].append(f"{f['match_id']} (not valued: {', '.join(missing)})")
                continue
            try:
                predictor = national() if comp == "nations_league" else club()
                kwargs = {"is_knockout": False} if comp == "nations_league" else {}
                baseline = predictor.predict_match(home, away, **kwargs)
            except Exception as exc:
                report["errors"].append(f"{f['match_id']}: {type(exc).__name__}: {exc}")
                continue
            share_h, share_a = shares["home"]["share"], shares["away"]["share"]
            before = _cached(f["match_id"])
            # The written scenario of the cached prediction; adjust() keeps it
            # only if the predicted result survives the line-ups.
            from src.poisson_model import SCENARIO_LANG
            before_markets = (before.get("score_prediction") or {}).get("betting_markets") or {}
            scenario = before_markets.get("scenario")
            if scenario and before_markets.get("scenario_lang") == SCENARIO_LANG:
                baseline.setdefault("score_prediction", {}).setdefault("betting_markets", {})["scenario"] = scenario
            fresh = lineups.adjust(baseline, share_h, share_a)
            fresh.update(lineup_refreshed_at=now.isoformat(),
                         lineup={side: ({k: v for k, v in info.items()} if info else None)
                                 for side, info in shares.items()},
                         probabilities_before_lineup={k: baseline[k] for k in keys},
                         probabilities_cached_before={k: before.get(k) for k in keys})
            _write(f, fresh)
            report["refreshed"].append(f["match_id"])
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return _report("hourly", report)

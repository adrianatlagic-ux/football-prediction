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
from typing import Callable

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
    scenario = ((previous.get("score_prediction") or {}).get("betting_markets") or {}).get("scenario")
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


def run_daily(club: Callable, national: Callable, morning_odds: Callable) -> dict:
    """Results, history, predictions for the next 48 hours, morning odds."""
    from scripts.refresh_squad_predictions import upcoming
    from src.results_update import update_club_results, update_national_results
    now = datetime.now(timezone.utc)
    report = {"started_at": now.isoformat(), "errors": []}
    with _lock:
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
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return _report("daily", report)


def run_hourly(club: Callable, national: Callable) -> dict:
    """Squad values for matches in the next 75 minutes, each match once."""
    from scripts.refresh_squad_predictions import (load_registry, refreshed_in_window, upcoming)
    from src.competitions import get as get_competition
    from src.squad_data import available_squad_values
    now = datetime.now(timezone.utc)
    report = {"started_at": now.isoformat(), "errors": [], "refreshed": []}
    with _lock:
        due = [f for f in upcoming(SQUAD_WINDOW_MINUTES, now)
               if not refreshed_in_window(f, SQUAD_WINDOW_MINUTES, None)]
        values = {}
        for key in {f["competition"] for f in due}:
            teams = sorted({t for f in due if f["competition"] == key for t in (f["home_team"], f["away_team"])})
            try:
                values.update(available_squad_values(teams, load_registry(key), get_competition(key),
                                                     as_of=now.date()))
            except Exception as exc:
                report["errors"].append(f"squads {key}: {type(exc).__name__}: {exc}")
        keys = ("probability_home_win", "probability_draw", "probability_away_win")
        for f in due:
            home, away = f["home_team"], f["away_team"]
            override = {t: values[t] for t in (home, away) if t in values}
            if not override:
                continue
            try:
                predictor = national() if f["competition"] == "nations_league" else club()
                kwargs = {"is_knockout": False} if f["competition"] == "nations_league" else {}
                baseline = predictor.predict_match(home, away, **kwargs)
                fresh = predictor.predict_match(home, away, market_values=override, **kwargs)
            except Exception as exc:
                report["errors"].append(f"{f['match_id']}: {type(exc).__name__}: {exc}")
                continue
            before = _cached(f["match_id"])
            scenario = ((before.get("score_prediction") or {}).get("betting_markets") or {}).get("scenario")
            if scenario:
                fresh.setdefault("score_prediction", {}).setdefault("betting_markets", {})["scenario"] = scenario
            fresh.update(squad_adjusted=True, squad_values_used={k: int(v) for k, v in override.items()},
                         squad_refreshed_at=now.isoformat(),
                         probabilities_cached_before={k: before.get(k) for k in keys},
                         probabilities_without_squad_data={k: baseline[k] for k in keys})
            _write(f, fresh)
            report["refreshed"].append(f["match_id"])
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return _report("hourly", report)

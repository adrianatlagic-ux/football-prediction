"""Recompute the next hour's fixtures from the squads that were named.

A cached prediction is built days ahead, when all anyone knows is which clubs
or nations are involved. By an hour before kickoff the squad is settled and
the injury list is current, so the strongest input the model has - what the
side is worth - can be replaced with what is actually available.

    python3 scripts/refresh_squad_predictions.py                # due fixtures
    python3 scripts/refresh_squad_predictions.py --dry-run      # show, fetch nothing
    python3 scripts/refresh_squad_predictions.py --window 180   # widen the window
    python3 scripts/refresh_squad_predictions.py --api https://football-prediction.fly.dev

This runs on a schedule, not on request. A page view should read a finished
answer rather than wait on a scraper and a model fit, so the result is written
back into data/predictions_cache/ and served from there like any other
prediction. One Apify run covers every team in the window.

With --api it also posts each prediction to a running deployment. That matters
because the container copies data/ in at build time: a commit to the cache
changes the repository and nothing the site serves, so without the upload the
refresh would reach no visitor until the next deploy. PREDICTION_WRITE_TOKEN
is sent as a header when set, and the deployment rejects the write without it.

What it does not do is decide anything. The squad value goes in as a feature;
how much it should move a probability was learned from matches where that
value was always the full-strength one, so treat the shift as a correction to
an input rather than as a measured effect.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.competitions import COMPETITIONS, get as get_competition
from src.squad_data import available_squad_values

CACHE = ROOT / "data" / "predictions_cache"
REGISTRY = ROOT / "data" / "team_registry.csv"
FIXTURE_FILES = {"cl": "cl_fixtures.json", "bl": "bl_fixtures.json", "nl": "nl_fixtures.json"}
# Which competition each fixture file belongs to.
FIXTURE_COMPETITION = {"cl": "champions_league", "bl": "bundesliga", "nl": "nations_league"}
DEFAULT_WINDOW_MINUTES = 75


def load_registry(competition_key: str) -> dict:
    with REGISTRY.open(encoding="utf-8") as fh:
        return {r["team"]: r["transfermarkt_id"] for r in csv.DictReader(fh)
                if r["competition"] == competition_key}


def upcoming(window_minutes: int, now: datetime) -> list:
    """Fixtures kicking off within the window, with their competition."""
    from zoneinfo import ZoneInfo
    berlin = ZoneInfo("Europe/Berlin")
    due = []
    for short, filename in FIXTURE_FILES.items():
        path = ROOT / "frontend" / "src" / filename
        if not path.exists():
            continue
        for fixture in json.loads(path.read_text(encoding="utf-8")):
            try:
                local = datetime.fromisoformat(f"{fixture['date']}T{fixture.get('time', '00:00')}")
            except (KeyError, ValueError):
                continue
            kickoff = local.replace(tzinfo=berlin).astimezone(timezone.utc)
            minutes = (kickoff - now).total_seconds() / 60
            if 0 < minutes <= window_minutes:
                due.append({**fixture, "competition": FIXTURE_COMPETITION[short],
                            "kickoff": kickoff, "minutes_to_kickoff": int(minutes)})
    return sorted(due, key=lambda f: f["kickoff"])


def refreshed_in_window(fixture: dict, window_minutes: int, api_base: str | None) -> bool:
    """Whether this match already got its squad refresh for this kickoff.

    The job runs every 15 minutes and a match stays in the 75-minute window
    for five runs; without this check each run would pay Apify for the same
    squads again. The scheduled job uploads to the live app and never
    commits, so its own checkout cannot tell - the live cache is asked.
    """
    import urllib.request
    try:
        if api_base:
            with urllib.request.urlopen(f"{api_base}/predictions/{fixture['match_id']}", timeout=15) as r:
                cached = json.loads(r.read())
        else:
            cached = json.loads((CACHE / f"{fixture['match_id']}.json").read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(cached["squad_refreshed_at"])
    except Exception:
        return False
    return (fixture["kickoff"] - stamp).total_seconds() / 60 <= window_minutes


def upload(api_base: str, match_id: str, payload: dict) -> bool:
    """Push one prediction to a deployment; False if it did not take."""
    import os
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json"}
    token = os.getenv("PREDICTION_WRITE_TOKEN", "")
    if token:
        headers["X-Prediction-Token"] = token
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/predictions/{match_id}",
        data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="refresh matches already refreshed in this window")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW_MINUTES,
                    help=f"minutes before kickoff to act (default {DEFAULT_WINDOW_MINUTES})")
    ap.add_argument("--api", default=None,
                    help="also upload each refreshed prediction to this deployment")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    due = [f for f in upcoming(args.window, now)
           if args.force or not refreshed_in_window(f, args.window, args.api)]
    print(f"{now:%H:%M} UTC | {len(due)} Spiel(e) im {args.window}-Minuten-Fenster")
    if not due:
        return
    for fixture in due:
        print(f"  {fixture['minutes_to_kickoff']:4} Min  {fixture['home_team']} - {fixture['away_team']}")
    if args.dry_run:
        print("\n--dry-run: nichts abgerufen, nichts geschrieben.")
        return

    # One fetch per competition covering every team due in this window.
    values: dict = {}
    for competition_key in {f["competition"] for f in due}:
        competition = get_competition(competition_key)
        teams = sorted({t for f in due if f["competition"] == competition_key
                        for t in (f["home_team"], f["away_team"])})
        try:
            found = available_squad_values(teams, load_registry(competition_key),
                                           competition, as_of=now.date())
        except Exception as exc:
            print(f"  FEHLER {competition_key}: {type(exc).__name__}: {exc}")
            continue
        print(f"\n  {competition.label}: {len(found)} von {len(teams)} Kadern bepreist")
        values.update(found)

    if not values:
        print("\nKeine Kaderwerte erhalten - Cache bleibt unveraendert.")
        return

    from src.predictor import FootballPredictor
    from src.club_predictor import ClubFootballPredictor, DEFAULT_MODEL_PATH
    from src.fifa_rankings import has_ranking

    national = club = None
    written = 0
    for fixture in due:
        home, away = fixture["home_team"], fixture["away_team"]
        override = {t: values[t] for t in (home, away) if t in values}
        if not override:
            print(f"  uebersprungen (kein Kaderwert): {home} - {away}")
            continue
        path = CACHE / f"{fixture['match_id']}.json"
        if not path.exists():
            print(f"  uebersprungen (nicht im Cache): {fixture['match_id']}")
            continue
        before = json.loads(path.read_text(encoding="utf-8"))
        # Run it twice: once as the model would have answered today without
        # any squad data, once with it. Comparing the new numbers against the
        # cached ones would credit the squads with every change since the
        # cache was written - including a retrained model, which on this
        # first run moved a fixture by fourteen points on its own.
        try:
            if has_ranking(home) and has_ranking(away):
                national = national or FootballPredictor(model_path=ROOT / "model.joblib")
                baseline = national.predict_match(home, away, is_knockout=False)
                fresh = national.predict_match(home, away, is_knockout=False, market_values=override)
            else:
                club = club or ClubFootballPredictor(model_path=DEFAULT_MODEL_PATH)
                baseline = club.predict_match(home, away)
                fresh = club.predict_match(home, away, market_values=override)
        except Exception as exc:
            print(f"  FEHLER {fixture['match_id']}: {type(exc).__name__}: {exc}")
            continue

        # Keep the pre-adjustment numbers alongside: without them nobody can
        # tell later whether the squad data moved anything or the model was
        # simply refitted in the meantime.
        fresh["squad_adjusted"] = True
        fresh["squad_values_used"] = {k: int(v) for k, v in override.items()}
        fresh["squad_refreshed_at"] = now.isoformat()
        keys = ("probability_home_win", "probability_draw", "probability_away_win")
        fresh["probabilities_cached_before"] = {k: before.get(k) for k in keys}
        fresh["probabilities_without_squad_data"] = {k: baseline[k] for k in keys}
        for key in ("match_id", "group", "date", "time"):
            if key in before:
                fresh.setdefault(key, before[key])
        path.write_text(json.dumps(fresh, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
        if args.api:
            uploaded = upload(args.api, fixture["match_id"], fresh)
            if not uploaded:
                print(f"    Upload fehlgeschlagen: {fixture['match_id']}")

        from_squads = max(abs(fresh[k] - baseline[k]) for k in keys)
        from_model = max(abs(baseline[k] - (before.get(k) or 0)) for k in keys)
        print(f"  {home[:18]:20} - {away[:18]:20} "
              f"{fresh['probability_home_win']:5.1%}/{fresh['probability_draw']:5.1%}/"
              f"{fresh['probability_away_win']:5.1%}  "
              f"Kader {from_squads:+.1%}  | seit Cache-Erstellung {from_model:.1%}")

    print(f"\n{written} Vorhersage(n) im Cache aktualisiert")


if __name__ == "__main__":
    main()

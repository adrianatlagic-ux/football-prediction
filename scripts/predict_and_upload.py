"""Generate predictions for a matchday and upload them to the live backend.

Replaces the n8n step that used to do this. Run before each matchday:

    python3 scripts/predict_and_upload.py 2026-06-27
    python3 scripts/predict_and_upload.py 2026-06-27 --api https://football-prediction.fly.dev
    python3 scripts/predict_and_upload.py 2026-06-27 --dry-run   # only print, don't upload

With no date, defaults to today (local date).
"""
import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor
from src.scenario_agent import generate_ai_scenario

FIXTURES_PATH = Path(__file__).parent.parent / "frontend" / "src" / "wc2026_fixtures.json"
DEFAULT_API = "https://football-prediction.fly.dev"


def upload(api_base: str, match_id: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base}/predictions/{match_id}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=date.today().isoformat(),
                         help="Matchday date, e.g. 2026-06-27 (default: today)")
    parser.add_argument("--api", default=DEFAULT_API, help="Backend base URL")
    parser.add_argument("--dry-run", action="store_true", help="Only print, don't upload")
    args = parser.parse_args()

    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    games = [f for f in fixtures if f["date"] == args.date]
    if not games:
        print(f"Keine Spiele am {args.date} gefunden.")
        return

    print(f"{len(games)} Spiel(e) am {args.date}. Lade Modell...")
    predictor = FootballPredictor(model_path="model.joblib")

    cache_dir = Path(__file__).parent.parent / "data" / "predictions_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    ok, failed = 0, []
    for f in games:
        is_knockout = "round of" in f.get("group", "").lower() or f.get("group", "") in (
            "Round of 16", "Quarter-final", "Semi-final", "Final",
        )
        try:
            result = predictor.predict_match(f["home_team"], f["away_team"], is_knockout=is_knockout)
        except Exception as exc:
            print(f"  FEHLER bei Vorhersage {f['home_team']} vs {f['away_team']}: {exc}")
            failed.append(f["match_id"])
            continue

        ai_scenario = generate_ai_scenario(result, f["home_team"], f["away_team"], is_knockout=is_knockout)
        if ai_scenario:
            result["score_prediction"]["betting_markets"]["scenario"] = ai_scenario

        cache_path = cache_dir / f"{f['match_id']}.json"
        cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        label = f"{f['home_team']:22} vs {f['away_team']:22}"
        probs = f"H{result['probability_home_win']:.0%} D{result['probability_draw']:.0%} A{result['probability_away_win']:.0%}"

        if args.dry_run:
            print(f"  [DRY RUN] {label} {probs}")
            continue

        try:
            upload(args.api, f["match_id"], result)
            print(f"  ✓ {label} {probs}  -> hochgeladen")
            ok += 1
        except Exception as exc:
            print(f"  FEHLER beim Upload von {f['match_id']}: {exc}")
            failed.append(f["match_id"])

    if not args.dry_run:
        print(f"\n{ok}/{len(games)} erfolgreich hochgeladen.")
        if failed:
            print(f"Fehlgeschlagen: {', '.join(failed)}")


if __name__ == "__main__":
    main()

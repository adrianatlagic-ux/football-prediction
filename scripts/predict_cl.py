"""Generate predictions for all current Champions League fixtures using the
club model, and save them to data/predictions_cache/ (same place/format the
API and frontend already read from for match cards).

    python3 scripts/predict_cl.py
    python3 scripts/predict_cl.py --api https://football-prediction.fly.dev  # also upload
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.club_predictor import ClubFootballPredictor
from src.scenario_agent import generate_ai_scenario

FIXTURES_PATH = Path(__file__).parent.parent / "frontend" / "src" / "cl_fixtures.json"
CACHE_DIR = Path(__file__).parent.parent / "data" / "predictions_cache"


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
    parser.add_argument("--api", default=None, help="If set, also upload to this backend URL")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    print(f"{len(fixtures)} Champions-League-Spiele. Lade Modell...")
    predictor = ClubFootballPredictor(model_path="club_model.joblib")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ok, failed = 0, []
    for f in fixtures:
        try:
            result = predictor.predict_match(f["home_team"], f["away_team"], is_knockout=False)
        except Exception as exc:
            print(f"  FEHLER bei {f['home_team']} vs {f['away_team']}: {exc}")
            failed.append(f["match_id"])
            continue

        ai_scenario = generate_ai_scenario(result, f["home_team"], f["away_team"], is_knockout=False)
        if ai_scenario:
            result["score_prediction"]["betting_markets"]["scenario"] = ai_scenario

        cache_path = CACHE_DIR / f"{f['match_id']}.json"
        cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        label = f"{f['home_team']:22} vs {f['away_team']:22}"
        probs = f"H{result['probability_home_win']:.0%} D{result['probability_draw']:.0%} A{result['probability_away_win']:.0%}"

        if args.api and not args.dry_run:
            try:
                upload(args.api, f["match_id"], result)
                print(f"  ✓ {label} {probs}  -> hochgeladen")
                ok += 1
            except Exception as exc:
                print(f"  FEHLER beim Upload von {f['match_id']}: {exc}")
                failed.append(f["match_id"])
        else:
            print(f"  {label} {probs}  -> gecacht")
            ok += 1

    print(f"\n{ok} ok, {len(failed)} fehlgeschlagen.")
    if failed:
        print("Fehlgeschlagen:", ", ".join(failed))


if __name__ == "__main__":
    main()

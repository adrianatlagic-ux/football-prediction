"""Train V2 once on data strictly before a season start, then predict every
match of that season with WALK-FORWARD features via predict_match(as_of=...)
- matchday 30 sees matchdays 1-29 of the real season, not a frozen
pre-season snapshot. The base models/combiner stay frozen from the
pre-season fit; only the feature inputs (form/Elo/H2H/market value) update
per match, same operating assumption as eval_v1_season.py.

Run from the codex-club-model-validation WORKTREE.

    python3 scripts/eval_v2_season.py --cutoff 2025-08-22 --fixtures data/season_2025_26_fixtures.json --out data/season_2025_26_v2_predictions.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.club_feature_engineering import build_features, prepare_history
from src.club_predictor import ClubFootballPredictor

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "club_football_results.csv"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", required=True, help="Season start date (YYYY-MM-DD); fitting uses data strictly before this")
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    cutoff = pd.Timestamp(args.cutoff)

    raw = pd.read_csv(DATA_PATH)
    raw = raw.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
    full_history = prepare_history(raw)

    pre_season = full_history[full_history.date < cutoff].reset_index(drop=True)
    print(f"V2 fitting on {len(pre_season)} matches strictly before {cutoff.date()}")

    features = build_features(pre_season)

    predictor = ClubFootballPredictor()
    predictor.fit_validated_recipe(pre_season, features, "stacked", half_life_days=545)
    print(f"Calibration window ends {predictor.fit_boundaries['calibration_end']}")

    # fit_validated_recipe stores the pre-season-only history it was given.
    # For walk-forward inference, predict_match's own as_of filtering needs
    # access to the season's already-played matches too - swap in the full
    # history now that fitting (which must not see them) is done. as_of on
    # each call still strictly filters to before that match's own date.
    predictor._history = full_history

    fixtures = json.loads(args.fixtures.read_text())
    predictions = []
    for i, fx in enumerate(fixtures):
        home, away = fx["home"], fx["away"]
        result = predictor.predict_match(home, away, as_of=fx["date"])
        predictions.append({
            "date": fx["date"], "home": home, "away": away,
            "home_goals": fx["home_goals"], "away_goals": fx["away_goals"],
            "probability_home_win": result["probability_home_win"],
            "probability_draw": result["probability_draw"],
            "probability_away_win": result["probability_away_win"],
        })
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(fixtures)}")

    args.out.write_text(json.dumps(predictions, indent=2, ensure_ascii=False))
    print(f"Wrote {len(predictions)} predictions -> {args.out}")


if __name__ == "__main__":
    main()

"""Train V1 once on data strictly before a season start, then predict every
match of that season with WALK-FORWARD features: each prediction's
form/H2H/goal-stat inputs use real results up to (not including) that
match's own date - so matchday 30 sees matchdays 1-29 of the real season,
not a frozen pre-season snapshot. The classifier weights themselves stay
frozen from the pre-season fit (matches how the live site actually
operates: features refresh continuously, the model is not retrained before
every single match).

Run from the BASE REPO checkout (genuine, untouched V1 code).

    python3 scripts/eval_v1_season.py --cutoff 2025-08-22 --fixtures data/season_2025_26_fixtures.json --out data/season_2025_26_v1_predictions.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.club_feature_engineering import build_features, build_prediction_row, get_feature_columns, encode_result
from src.poisson_model import predict_scorelines
from src.models.ensemble_model import EnsemblePredictor
from src.club_predictor import POISSON_BLEND

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "club_football_results.csv"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", required=True, help="Season start date (YYYY-MM-DD); training uses data strictly before this")
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    cutoff = pd.Timestamp(args.cutoff)

    raw = pd.read_csv(DATA_PATH, parse_dates=["date"])
    raw = raw.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
    full_history = raw.sort_values("date").reset_index(drop=True)
    full_history["result"] = full_history.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)

    pre_season = full_history[full_history.date < cutoff].reset_index(drop=True)
    print(f"V1 fitting on {len(pre_season)} matches strictly before {cutoff.date()}")

    features = build_features(pre_season)
    feature_cols = get_feature_columns(features)

    half_life_days = 545
    days_ago = (cutoff - pre_season["date"]).dt.days.clip(lower=0).values
    weights = np.exp(-np.log(2) / half_life_days * days_ago)
    weights = weights / weights.mean()

    model = EnsemblePredictor()
    model.fit(features[feature_cols], features["result"], sample_weight=weights)

    fixtures = json.loads(args.fixtures.read_text())
    predictions = []
    for i, fx in enumerate(fixtures):
        home, away = fx["home"], fx["away"]
        fx_date = pd.Timestamp(fx["date"])
        # Walk-forward: history strictly before this fixture's own date,
        # including any of the current season's matches already played.
        history_so_far = full_history[full_history.date < fx_date]

        X = build_prediction_row(history_so_far, home, away)
        for col in feature_cols:
            if col not in X.columns:
                X[col] = 0.0
        X = X[feature_cols]

        clf_proba = model.predict_proba(X)[0]
        poisson_pre = predict_scorelines(history_so_far, home, away)
        poi_proba = [poisson_pre["probability_home_win"], poisson_pre["probability_draw"], poisson_pre["probability_away_win"]]
        blended = [(1 - POISSON_BLEND) * c + POISSON_BLEND * p for c, p in zip(clf_proba, poi_proba)]
        total = sum(blended) or 1.0
        blended = [b / total for b in blended]

        predictions.append({
            "date": fx["date"], "home": home, "away": away,
            "home_goals": fx["home_goals"], "away_goals": fx["away_goals"],
            "probability_home_win": blended[0], "probability_draw": blended[1], "probability_away_win": blended[2],
        })
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(fixtures)}")

    args.out.write_text(json.dumps(predictions, indent=2, ensure_ascii=False))
    print(f"Wrote {len(predictions)} predictions -> {args.out}")


if __name__ == "__main__":
    main()

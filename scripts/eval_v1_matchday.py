"""Train V1 (production architecture: classifier + Poisson blend, static
current market values, no Elo) on all data strictly before the 2026/27
Bundesliga season start, then predict the real matchday 1+2 fixtures.

Run from the BASE REPO checkout (genuine, untouched V1 code) - not from the
codex-club-model-validation worktree, which has V2's refactored modules
under the same module names.

    python3 scripts/eval_v1_matchday.py

Writes data/matchday_1_2_v1_predictions.json.
"""
from __future__ import annotations

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

CUTOFF = pd.Timestamp("2026-08-28")  # 2026/27 Bundesliga season start (matchday 1)
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "club_football_results.csv"
FIXTURES_PATH = Path(__file__).resolve().parents[1] / "data" / "matchday_1_2_2026_27_fixtures.json"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "matchday_1_2_v1_predictions.json"


def main():
    raw = pd.read_csv(DATA_PATH, parse_dates=["date"])
    raw = raw.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
    history = raw[raw.date < CUTOFF].sort_values("date").reset_index(drop=True)
    history["result"] = history.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)
    print(f"V1 training on {len(history)} matches strictly before {CUTOFF.date()}")

    features = build_features(history)
    feature_cols = get_feature_columns(features)

    # Same recency-decay formula as ClubFootballPredictor._compute_sample_weights,
    # but anchored to the backtest cutoff instead of wall-clock "now" - using
    # today's date here would give matches closer to today (irrelevant for
    # this backtest) more weight than matches close to the actual prediction
    # point, which is the cutoff, not today.
    half_life_days = 545
    days_ago = (CUTOFF - history["date"]).dt.days.clip(lower=0).values
    weights = np.exp(-np.log(2) / half_life_days * days_ago)
    weights = weights / weights.mean()

    model = EnsemblePredictor()
    model.fit(features[feature_cols], features["result"], sample_weight=weights)

    fixtures = json.loads(FIXTURES_PATH.read_text())
    predictions = []
    for fx in fixtures:
        home, away = fx["home"], fx["away"]
        X = build_prediction_row(history, home, away)
        for col in feature_cols:
            if col not in X.columns:
                X[col] = 0.0
        X = X[feature_cols]

        clf_proba = model.predict_proba(X)[0]
        poisson_pre = predict_scorelines(history, home, away)
        poi_proba = [poisson_pre["probability_home_win"], poisson_pre["probability_draw"], poisson_pre["probability_away_win"]]
        blended = [(1 - POISSON_BLEND) * c + POISSON_BLEND * p for c, p in zip(clf_proba, poi_proba)]
        total = sum(blended) or 1.0
        blended = [b / total for b in blended]

        predictions.append({
            "matchday": fx["matchday"], "date": fx["date"], "home": home, "away": away,
            "home_goals": fx["home_goals"], "away_goals": fx["away_goals"],
            "probability_home_win": blended[0], "probability_draw": blended[1], "probability_away_win": blended[2],
        })

    OUT_PATH.write_text(json.dumps(predictions, indent=2, ensure_ascii=False))
    print(f"Wrote {len(predictions)} predictions -> {OUT_PATH}")


if __name__ == "__main__":
    main()

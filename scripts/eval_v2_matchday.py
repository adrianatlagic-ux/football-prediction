"""Train V2 (stacked recipe: dated Elo/form/market-value features, fitted
calibration) on all data strictly before the 2026/27 Bundesliga season
start, then predict the real matchday 1+2 fixtures.

Run from the codex-club-model-validation WORKTREE (has ClubElo,
club_validation, the dated market-value pipeline) - not the base repo.

    python3 scripts/eval_v2_matchday.py

Writes data/matchday_1_2_v2_predictions.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.club_feature_engineering import build_features, prepare_history
from src.club_predictor import ClubFootballPredictor

CUTOFF = pd.Timestamp("2026-08-28")  # 2026/27 Bundesliga season start (matchday 1)
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "club_football_results.csv"
FIXTURES_PATH = Path(__file__).resolve().parents[1] / "data" / "matchday_1_2_2026_27_fixtures.json"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "matchday_1_2_v2_predictions.json"


def main():
    raw = pd.read_csv(DATA_PATH)
    raw = raw.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
    history = prepare_history(raw)
    history = history[history.date < CUTOFF].reset_index(drop=True)
    print(f"V2 training on {len(history)} matches strictly before {CUTOFF.date()}")

    features = build_features(history)

    predictor = ClubFootballPredictor()
    predictor.fit_validated_recipe(history, features, "stacked", half_life_days=545)
    print(f"Calibration window ends {predictor.fit_boundaries['calibration_end']}")

    fixtures = json.loads(FIXTURES_PATH.read_text())
    predictions = []
    for fx in fixtures:
        home, away = fx["home"], fx["away"]
        result = predictor.predict_match(home, away, as_of=fx["date"])
        predictions.append({
            "matchday": fx["matchday"], "date": fx["date"], "home": home, "away": away,
            "home_goals": fx["home_goals"], "away_goals": fx["away_goals"],
            "probability_home_win": result["probability_home_win"],
            "probability_draw": result["probability_draw"],
            "probability_away_win": result["probability_away_win"],
        })

    OUT_PATH.write_text(json.dumps(predictions, indent=2, ensure_ascii=False))
    print(f"Wrote {len(predictions)} predictions -> {OUT_PATH}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import joblib
import pandas as pd
import numpy as np
from pathlib import Path

from .data_loader import load_completed_matches
from .feature_engineering import build_features, build_prediction_row, get_feature_columns
from .models.ensemble_model import EnsemblePredictor
from .evaluation import evaluate

RESULT_LABELS = {"H": "Home Win", "D": "Draw", "A": "Away Win"}


class FootballPredictor:
    def __init__(self, model_path: str | Path | None = None):
        self.model = EnsemblePredictor()
        self._feature_cols: list[str] = []
        self._trained = False
        self._history: pd.DataFrame | None = None

        if model_path and Path(model_path).exists():
            self.load(model_path)

    def train(self, since_year: int = 1990, test_size: float = 0.2) -> dict:
        df_raw = load_completed_matches()
        df_raw = df_raw[df_raw["date"].dt.year >= since_year].reset_index(drop=True)
        self._history = df_raw

        print(f"Building features for {len(df_raw):,} matches since {since_year}...")
        features = build_features(df_raw)
        self._feature_cols = get_feature_columns(features)

        split = int(len(features) * (1 - test_size))
        train, test = features.iloc[:split], features.iloc[split:]

        self.model.fit(train[self._feature_cols], train["result"])
        self._trained = True

        y_pred = self.model.predict(test[self._feature_cols])
        y_proba = self.model.predict_proba(test[self._feature_cols])
        return evaluate(test["result"], y_pred, y_proba)

    def predict_match(self, home_team: str, away_team: str, neutral: bool = True) -> dict:
        if not self._trained:
            raise RuntimeError("Model not trained. Call .train() first.")

        X = build_prediction_row(self._history, home_team, away_team, neutral=neutral)

        for col in self._feature_cols:
            if col not in X.columns:
                X[col] = 0.0

        X = X[self._feature_cols]
        result = self.model.predict_match(X)

        return {
            "home_team": home_team,
            "away_team": away_team,
            "prediction": result["prediction"],
            "prediction_label": RESULT_LABELS[result["prediction"]],
            "probability_home_win": result["probability_home_win"],
            "probability_draw": result["probability_draw"],
            "probability_away_win": result["probability_away_win"],
        }

    def save(self, path: str | Path) -> None:
        joblib.dump({
            "model": self.model,
            "feature_cols": self._feature_cols,
            "history": self._history,
        }, path)

    def load(self, path: str | Path) -> None:
        payload = joblib.load(path)
        self.model = payload["model"]
        self._feature_cols = payload["feature_cols"]
        self._history = payload.get("history")
        self._trained = True

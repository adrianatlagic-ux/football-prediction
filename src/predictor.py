from __future__ import annotations

import joblib
import pandas as pd
import numpy as np
from pathlib import Path

from .data_loader import load_sample_data, load_csv
from .feature_engineering import build_features, get_feature_columns
from .models.ensemble_model import EnsemblePredictor
from .evaluation import evaluate


class FootballPredictor:
    def __init__(self, model_path: str | Path | None = None):
        self.model = EnsemblePredictor()
        self._feature_cols: list[str] = []
        self._trained = False

        if model_path and Path(model_path).exists():
            self.load(model_path)

    def train(self, data_path: str | Path | None = None, test_size: float = 0.2) -> dict:
        df_raw = load_csv(data_path) if data_path else load_sample_data()
        features = build_features(df_raw)
        self._feature_cols = get_feature_columns(features)

        split = int(len(features) * (1 - test_size))
        train, test = features.iloc[:split], features.iloc[split:]

        X_train = train[self._feature_cols]
        y_train = train["result"]
        X_test = test[self._feature_cols]
        y_test = test["result"]

        self.model.fit(X_train, y_train)
        self._trained = True

        y_pred = self.model.predict(X_test)
        y_proba = self.model.predict_proba(X_test)
        return evaluate(y_test, y_pred, y_proba)

    def predict_match(self, home_team: str, away_team: str, data_path: str | Path | None = None) -> dict:
        if not self._trained:
            raise RuntimeError("Model is not trained. Call .train() first.")

        df_raw = load_csv(data_path) if data_path else load_sample_data()
        features = build_features(df_raw)

        synthetic_row = {c: 0.0 for c in self._feature_cols}
        synthetic_row.update(self._build_prediction_features(df_raw, home_team, away_team))

        X = pd.DataFrame([synthetic_row])[self._feature_cols]
        return {"home_team": home_team, "away_team": away_team, **self.model.predict_match(X)}

    def save(self, path: str | Path) -> None:
        joblib.dump({"model": self.model, "feature_cols": self._feature_cols}, path)

    def load(self, path: str | Path) -> None:
        payload = joblib.load(path)
        self.model = payload["model"]
        self._feature_cols = payload["feature_cols"]
        self._trained = True

    def _build_prediction_features(self, df_raw: pd.DataFrame, home: str, away: str) -> dict:
        from .feature_engineering import _team_form, _h2h_stats, _goal_stats
        result: dict = {}
        result.update(_team_form(df_raw, home, prefix="home"))
        result.update(_team_form(df_raw, away, prefix="away"))
        result.update(_h2h_stats(df_raw, home, away))
        result.update(_goal_stats(df_raw, home, prefix="home"))
        result.update(_goal_stats(df_raw, away, prefix="away"))
        return result

from __future__ import annotations

import numpy as np
import pandas as pd

from .base_model import BasePredictor
from .random_forest_model import RandomForestPredictor
from .xgboost_model import XGBoostPredictor


class EnsemblePredictor(BasePredictor):
    def __init__(self, weights: list[float] | None = None):
        self.predictors: list[BasePredictor] = [
            RandomForestPredictor(),
            XGBoostPredictor(),
        ]
        self.weights = weights or [0.5, 0.5]
        assert len(self.weights) == len(self.predictors)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "EnsemblePredictor":
        for p in self.predictors:
            p.fit(X, y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        probas = np.stack([p.predict_proba(X) for p in self.predictors], axis=0)
        weights = np.array(self.weights)[:, None, None]
        return (probas * weights).sum(axis=0)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.predict_proba(X)
        indices = np.argmax(proba, axis=1)
        return np.array(self.CLASSES)[indices]

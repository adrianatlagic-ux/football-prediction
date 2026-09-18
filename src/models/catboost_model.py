from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

from .base_model import BasePredictor


class CatBoostPredictor(BasePredictor):
    """Same hyperparameters as club_validation.py's catboost_elo candidate.
    CatBoost exposes its own class_ order (not guaranteed H/D/A) - remapped
    on every predict_proba call, same fix Codex applied for the benchmark."""

    def __init__(self, random_state: int = 42):
        from catboost import CatBoostClassifier
        self.model = CatBoostClassifier(
            iterations=350, depth=4, learning_rate=0.04, loss_function="MultiClass",
            l2_leaf_reg=5, random_seed=random_state, verbose=False,
            allow_writing_files=False, thread_count=4,
        )
        self._le = LabelEncoder()
        self._le.classes_ = np.array(self.CLASSES)

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray | None = None) -> "CatBoostPredictor":
        y_enc = self._le.transform(y)
        self.model.fit(X, y_enc, sample_weight=sample_weight)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._le.inverse_transform(self._ordered_proba(X).argmax(axis=1))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self._ordered_proba(X)

    def _ordered_proba(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.model.predict_proba(X)
        order = [int(c) for c in self.model.classes_]
        return proba[:, [order.index(i) for i in range(3)]]

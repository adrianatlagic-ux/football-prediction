from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

from .base_model import BasePredictor


class RandomForestPredictor(BasePredictor):
    def __init__(self, n_estimators: int = 300, max_depth: int | None = None, random_state: int = 42):
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        )
        self._le = LabelEncoder()
        self._le.classes_ = np.array(self.CLASSES)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "RandomForestPredictor":
        y_enc = self._le.transform(y)
        self.model.fit(X, y_enc)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._le.inverse_transform(self.model.predict(X))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X)

    def feature_importances(self, feature_names: list[str]) -> pd.Series:
        return pd.Series(self.model.feature_importances_, index=feature_names).sort_values(ascending=False)

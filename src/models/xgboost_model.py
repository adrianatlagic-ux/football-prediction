from __future__ import annotations

import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.preprocessing import LabelEncoder

from .base_model import BasePredictor


class XGBoostPredictor(BasePredictor):
    def __init__(self, n_estimators: int = 500, learning_rate: float = 0.05, max_depth: int = 5, random_state: int = 42):
        self.model = XGBClassifier(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            max_depth=max_depth,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="mlogloss",
            random_state=random_state,
            n_jobs=-1,
        )
        self._le = LabelEncoder()
        self._le.classes_ = np.array(self.CLASSES)

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: np.ndarray | None = None) -> "XGBoostPredictor":
        y_enc = self._le.transform(y)
        self.model.fit(X, y_enc, sample_weight=sample_weight, verbose=False)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._le.inverse_transform(self.model.predict(X))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X)

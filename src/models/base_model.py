from __future__ import annotations

from abc import ABC, abstractmethod
import numpy as np
import pandas as pd


class BasePredictor(ABC):
    CLASSES = ["H", "D", "A"]

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BasePredictor": ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray: ...

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...

    def predict_match(self, X: pd.DataFrame) -> dict:
        proba = self.predict_proba(X)[0]
        pred = self.CLASSES[int(np.argmax(proba))]
        return {
            "prediction": pred,
            "probability_home_win": round(float(proba[0]), 4),
            "probability_draw": round(float(proba[1]), 4),
            "probability_away_win": round(float(proba[2]), 4),
        }

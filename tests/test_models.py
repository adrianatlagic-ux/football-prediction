import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import numpy as np
import pandas as pd
from src.models.random_forest_model import RandomForestPredictor
from src.models.xgboost_model import XGBoostPredictor
from src.models.ensemble_model import EnsemblePredictor


def _make_data(n: int = 200):
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.random((n, 10)), columns=[f"f{i}" for i in range(10)])
    y = pd.Series(rng.choice(["H", "D", "A"], size=n))
    return X, y


@pytest.mark.parametrize("ModelCls", [RandomForestPredictor, XGBoostPredictor, EnsemblePredictor])
def test_fit_predict(ModelCls):
    X, y = _make_data()
    model = ModelCls()
    model.fit(X, y)
    preds = model.predict(X)
    assert set(preds).issubset({"H", "D", "A"})
    assert len(preds) == len(y)


@pytest.mark.parametrize("ModelCls", [RandomForestPredictor, XGBoostPredictor, EnsemblePredictor])
def test_proba_shape_and_sums(ModelCls):
    X, y = _make_data()
    model = ModelCls()
    model.fit(X, y)
    proba = model.predict_proba(X)
    assert proba.shape == (len(X), 3)
    assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_predict_match_keys():
    X, y = _make_data()
    model = RandomForestPredictor()
    model.fit(X, y)
    result = model.predict_match(X.head(1))
    assert "prediction" in result
    assert "probability_home_win" in result
    assert result["prediction"] in {"H", "D", "A"}

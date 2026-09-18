"""Chronological validation, explicit H/D/A order and held-out calibration."""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import softmax
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .club_poisson import ClubPoisson
from .club_feature_engineering import get_feature_columns
from .models.ensemble_model import EnsemblePredictor

CLASSES = np.array(["H", "D", "A"])
BASE_NAMES = ["ensemble_without_elo", "ensemble_elo", "random_forest_elo", "xgboost_elo", "logistic_elo", "catboost_elo", "poisson"]
CANDIDATES = BASE_NAMES + ["blend_30", "blend_tuned", "blend_calibrated", "stacked"]


def encode(y):
    return np.array([{"H": 0, "D": 1, "A": 2}[v] for v in y], dtype=int)


def normalize(p):
    p = np.asarray(p, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3 or not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("Expected finite nonnegative H/D/A probabilities")
    p = np.clip(p, 1e-12, 1)
    return p / p.sum(axis=1, keepdims=True)


def nll(y, p):
    p = normalize(p)
    return float(-np.log(p[np.arange(len(y)), encode(y)]).mean())


def metrics(y, p):
    p = normalize(p)
    truth = encode(y)
    confidence = p.max(axis=1)
    correct = p.argmax(axis=1) == truth
    bins = []
    for i in range(10):
        mask = (confidence >= i / 10) & (confidence < (i + 1) / 10 if i < 9 else confidence <= 1)
        if mask.any():
            bins.append({"lower": i / 10, "n": int(mask.sum()),
                         "confidence": float(confidence[mask].mean()), "hit_rate": float(correct[mask].mean())})
    return {"n": len(y), "accuracy": float(correct.mean()), "log_loss": nll(y, p),
            # Multiclass sum, range 0..2 (not the binary Brier convention).
            "brier_score": float(np.sum((p - np.eye(3)[truth]) ** 2, axis=1).mean()),
            "ece": sum(b["n"] * abs(b["confidence"] - b["hit_rate"]) for b in bins) / len(y),
            "calibration_bins": bins}


def split_dates(frame, tail_fraction):
    dates = np.sort(frame.date.unique())
    if len(dates) < 5 or not 0 < tail_fraction < 1:
        raise ValueError("Need >=5 dates and a fraction between 0 and 1")
    cutoff = dates[min(len(dates) - 1, max(1, int(len(dates) * (1 - tail_fraction))))]
    return frame[frame.date < cutoff], frame[frame.date >= cutoff]


def sample_weights(history, half_life_days=545):
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    days = (history.date.max() - history.date).dt.days.to_numpy()
    w = np.exp(-np.log(2) * days / half_life_days)
    return w / w.mean()


class BaseForecasts:
    def __init__(self, half_life_days=545):
        self.half_life_days = half_life_days

    def fit(self, history, features):
        from catboost import CatBoostClassifier

        self.columns = get_feature_columns(features)
        self.basic_columns = [c for c in self.columns if "elo" not in c]
        self.trained_through = history.date.max()
        weights = sample_weights(history, self.half_life_days)
        y = features.result
        self.models = {}
        for name in ("ensemble_without_elo", "ensemble_elo"):
            cols = self.basic_columns if name.endswith("without_elo") else self.columns
            self.models[name] = EnsemblePredictor().fit(features[cols], y, sample_weight=weights)
        self.models["logistic_elo"] = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=1000))
        self.models["logistic_elo"].fit(features[self.columns], encode(y), logisticregression__sample_weight=weights)
        self.models["catboost_elo"] = CatBoostClassifier(
            iterations=350, depth=4, learning_rate=0.04, loss_function="MultiClass",
            l2_leaf_reg=5, random_seed=42, verbose=False, allow_writing_files=False, thread_count=4,
        )
        self.models["catboost_elo"].fit(features[self.columns], encode(y), sample_weight=weights)
        self.poisson = ClubPoisson(half_life_days=self.half_life_days).fit(history)
        self.prior = (np.bincount(encode(y), minlength=3) + 1) / (len(y) + 3)
        return self

    def predict(self, features, fixtures):
        result = {}
        for name, model in self.models.items():
            cols = self.basic_columns if name == "ensemble_without_elo" else self.columns
            p = model.predict_proba(features[cols])
            # sklearn/CatBoost expose their output class order explicitly.
            if name in ("logistic_elo", "catboost_elo"):
                order = list(model.classes_)
                p = p[:, [order.index(i) for i in range(3)]]
            result[name] = normalize(p)
        result["poisson"] = normalize(self.poisson.predict_proba(fixtures))
        for name, model in zip(("random_forest_elo", "xgboost_elo"), self.models["ensemble_elo"].predictors):
            result[name] = normalize(model.predict_proba(features[self.columns]))
        result["frequency_baseline"] = np.tile(self.prior, (len(fixtures), 1))
        return result


class ProbabilityCombiner:
    """Parameters learned only from the chronological calibration segment."""
    def fit(self, y, p):
        clf, poi = p["ensemble_elo"], p["poisson"]
        fit = minimize_scalar(lambda w: nll(y, (1 - w) * clf + w * poi), bounds=(0, 1), method="bounded")
        choices = [0.0, float(fit.x), 1.0]
        self.poisson_weight = min(choices, key=lambda w: nll(y, (1 - w) * clf + w * poi))
        blend = (1 - self.poisson_weight) * clf + self.poisson_weight * poi
        self.temperature = float(minimize_scalar(
            lambda t: nll(y, softmax(np.log(blend.clip(1e-12)) / t, axis=1)),
            bounds=(0.5, 3.0), method="bounded",
        ).x)
        stacked = np.stack([p[n] for n in BASE_NAMES], axis=0)
        uniform = np.full(len(BASE_NAMES), 1 / len(BASE_NAMES))
        fit = minimize(lambda w: nll(y, np.tensordot(w, stacked, axes=1)) + 0.01 * np.sum((w - uniform) ** 2),
                       uniform, bounds=[(0, 1)] * len(BASE_NAMES),
                       constraints={"type": "eq", "fun": lambda w: w.sum() - 1}, method="SLSQP")
        if not fit.success:
            raise RuntimeError(f"Stacking fit failed: {fit.message}")
        self.stack_weights = np.clip(fit.x, 0, 1)
        self.stack_weights /= self.stack_weights.sum()
        return self

    def transform(self, p):
        result = dict(p)
        clf, poi = p["ensemble_elo"], p["poisson"]
        result["blend_30"] = normalize(0.7 * clf + 0.3 * poi)
        result["blend_tuned"] = normalize((1 - self.poisson_weight) * clf + self.poisson_weight * poi)
        result["blend_calibrated"] = softmax(np.log(result["blend_tuned"]) / self.temperature, axis=1)
        result["stacked"] = normalize(sum(w * p[n] for w, n in zip(self.stack_weights, BASE_NAMES)))
        return result

    def parameters(self):
        return {"poisson_weight": self.poisson_weight, "temperature": self.temperature,
                "stack_weights": dict(zip(BASE_NAMES, map(float, self.stack_weights)))}


def fit_calibrated(history, features, half_life_days=545):
    train, calibration = split_dates(features, 0.15)
    if set(train.result) != set(CLASSES):
        raise ValueError("Training segment must contain H, D and A")
    base = BaseForecasts(half_life_days).fit(history.loc[train.index], train)
    p = base.predict(calibration, history.loc[calibration.index])
    combiner = ProbabilityCombiner().fit(calibration.result, p)
    boundaries = {"training_end": str(train.date.max().date()),
                  "calibration_start": str(calibration.date.min().date()),
                  "calibration_end": str(calibration.date.max().date()),
                  "training_n": len(train), "calibration_n": len(calibration)}
    return base, combiner, boundaries

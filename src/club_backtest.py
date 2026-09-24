"""Fixed RF/XGB/CatBoost recipe; calibration and refits stay before cutoff."""
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from .models.ensemble_model import EnsemblePredictor
from .models.catboost_model import CatBoostPredictor
from .poisson_model import predict_scorelines, RATING_ITERATIONS, RATING_SHRINKAGE_K

ORDER = np.array(["H", "D", "A"])


def probabilities_metrics(y, p):
    p = np.asarray(p, dtype=float)
    p = p.clip(1e-12, 1)
    p /= p.sum(axis=1, keepdims=True)
    yi = np.array([{"H": 0, "D": 1, "A": 2}[v] for v in y])
    return {"n": len(y), "accuracy": float((p.argmax(axis=1) == yi).mean()),
            "log_loss": float(-np.log(p[np.arange(len(yi)), yi]).mean()),
            "brier": float(np.mean(np.sum((p - np.eye(3)[yi]) ** 2, axis=1)))}


def rating_context(past):
    """Equivalent opponent-strength iterations, vectorized once per date."""
    if past.empty:
        raise ValueError("Poisson requires past matches")
    recent = past[past.date >= past.date.max() - pd.Timedelta(days=3 * 365)]
    teams = sorted(set(recent.home_team) | set(recent.away_team))
    lookup = {t: i for i, t in enumerate(teams)}
    h = recent.home_team.map(lookup).to_numpy()
    a = recent.away_team.map(lookup).to_numpy()
    hg, ag = recent.home_goals.to_numpy(), recent.away_goals.to_numpy()
    n = len(teams)
    average = float(np.r_[hg, ag].mean())
    attack, defense = np.ones(n), np.ones(n)
    scored = np.bincount(np.r_[h, a], weights=np.r_[hg, ag], minlength=n)
    conceded = np.bincount(np.r_[h, a], weights=np.r_[ag, hg], minlength=n)
    for _ in range(RATING_ITERATIONS):
        denom_a = np.bincount(np.r_[h, a], weights=average * np.r_[defense[a], defense[h]], minlength=n)
        denom_d = np.bincount(np.r_[h, a], weights=average * np.r_[attack[a], attack[h]], minlength=n)
        attack = np.divide(scored, denom_a, out=attack.copy(), where=denom_a > 0)
        defense = np.divide(conceded, denom_d, out=defense.copy(), where=denom_d > 0)
    count = np.bincount(np.r_[h, a], minlength=n)
    shrink = count / (count + RATING_SHRINKAGE_K)
    ratings = {t: (float(1 + shrink[i] * (attack[i] - 1)), float(1 + shrink[i] * (defense[i] - 1))) for t, i in lookup.items()}
    return float(past[["home_goals", "away_goals"]].to_numpy().mean()), ratings


def poisson_for_dates(history, fixtures):
    result = {}
    for date, day in fixtures.groupby("date", sort=True):
        past = history[history.date < date]
        context = rating_context(past)
        for r in day.itertuples():
            result[r.Index] = predict_scorelines(past, r.home_team, r.away_team,
                                                 club_mode=True, rating_context=context)
    return result


def make_ensemble():
    model = EnsemblePredictor()
    model.predictors.append(CatBoostPredictor())
    model.weights = [1 / 3] * 3
    return model


def fit_estimator(history, X):
    ages = (history.date.max() - history.date).dt.days.to_numpy()
    weights = np.exp(-np.log(2) * ages / 545)
    weights /= weights.mean()
    return make_ensemble().fit(X, history.result, sample_weight=weights)


class CalibratedClubModel:
    def fit(self, history, X, cutoff, poisson_probs):
        cutoff = pd.Timestamp(cutoff).normalize()
        prior = history[history.date < cutoff]
        # 90-day holdout; expand if the off-season leaves too few matches.
        cal_start = cutoff - pd.Timedelta(days=90)
        dates = np.sort(prior.date.unique())
        if len(prior[prior.date >= cal_start]) < 150:
            cal_start = pd.Timestamp(dates[max(1, int(len(dates) * 0.85))])
        core = prior[prior.date < cal_start]
        calibration = prior[prior.date >= cal_start]
        if len(core) < 300 or len(calibration) < 30:
            raise ValueError("Insufficient chronological training/calibration data")
        calibration_model = fit_estimator(core, X.loc[core.index])
        p = 0.7 * calibration_model.predict_proba(X.loc[calibration.index]) + 0.3 * poisson_probs[calibration.index]
        objective = lambda t: probabilities_metrics(calibration.result, softmax(np.log(p.clip(1e-12)) / t, axis=1))["log_loss"]
        fit = minimize_scalar(objective, bounds=(0.5, 3.0), method="bounded")
        self.temperature = float(fit.x)
        # Refit on ALL available earlier matches. Temperature was learned
        # from prequential held-out predictions, not in-sample predictions.
        # Any confidence shift from this refit is measured by the outer test.
        self.model = fit_estimator(prior, X.loc[prior.index])
        self.feature_columns = list(X.columns)
        self.metadata = {"cutoff": str(cutoff.date()), "training_end": str(prior.date.max().date()),
                         "calibration_model_training_end": str(core.date.max().date()),
                         "calibration_start": str(calibration.date.min().date()),
                         "calibration_end": str(calibration.date.max().date()),
                         "training_n": len(prior), "temperature": self.temperature}
        return self

    def predict(self, X, poisson_probs):
        raw = 0.7 * self.model.predict_proba(X[self.feature_columns]) + 0.3 * poisson_probs
        return raw, softmax(np.log(raw.clip(1e-12)) / self.temperature, axis=1)

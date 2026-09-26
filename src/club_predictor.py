from __future__ import annotations

import os

import joblib
import pandas as pd
import numpy as np
from pathlib import Path

from .club_data_loader import load_completed_matches
from .club_market_value_policy import DEFAULT_POLICY as MARKET_VALUE_POLICY
from .poisson_model import predict_scorelines
from .game_flow import predict_game_flow
from .models.ensemble_model import EnsemblePredictor
from .models.catboost_model import CatBoostPredictor
from .evaluation import evaluate

RESULT_LABELS = {"H": "Home Win", "D": "Draw", "A": "Away Win"}

# One source of truth for the artifact, shared by the API and the prediction
# scripts. They drifted apart before: the scripts still loaded a pre-V3 model
# that this class now rejects outright, so they failed at run time instead of
# silently serving stale predictions - but only because the rejection exists.
DEFAULT_MODEL_PATH = Path(os.getenv("MODEL_PATH", "club_model_v3.joblib"))

# Fixed starting weight. Historical same-test tuning is not proof of optimality.
POISSON_BLEND = 0.30


def _build_ensemble() -> EnsemblePredictor:
    # Retain the existing equal-weight recipe; no profitable edge established.
    model = EnsemblePredictor()
    model.predictors.append(CatBoostPredictor())
    model.weights = [1 / 3, 1 / 3, 1 / 3]
    return model


class ClubFootballPredictor:
    """Same architecture as FootballPredictor (src/predictor.py) - ensemble
    classifier blended with a Poisson scoreline model - but for club football
    instead of national teams. Real differences from the WC model:

    1. No FIFA ranking feature (that dataset only covers national squads).
       Squad market value DOES have a club equivalent (src/club_market_values
       _dated.py, dated Transfermarkt snapshots, Germany-only so far).
    2. No neutral-venue / host-nation logic - club matches are always played
       at a real home ground (Champions League included), so home advantage
       is just an ordinary model feature, not a special case to switch off.
    3. Ensemble includes CatBoost alongside RF/XGBoost (see _build_ensemble).
    """

    def __init__(self, model_path: str | Path | None = None):
        self.model = _build_ensemble()
        self._feature_cols: list[str] = []
        self._trained = False
        self._history: pd.DataFrame | None = None
        self.schema_version = 3
        self.bundle = None
        self.calibrated = True

        if model_path and Path(model_path).exists():
            self.load(model_path)

    def train(self, test_size: float = 0.2, data_path=None) -> dict:
        from .club_features_v3 import prepare_history, build_features as dated_features
        from .club_backtest import CalibratedClubModel, poisson_for_dates, ORDER
        if not 0 < test_size < 1:
            raise ValueError("test_size must be between 0 and 1")
        raw = load_completed_matches() if data_path is None else pd.read_csv(data_path).rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
        history = prepare_history(raw)
        X = dated_features(history)
        dates = sorted(history.date.unique())
        cutoff = pd.Timestamp(dates[int(len(dates) * (1 - test_size))])
        test = history[history.date >= cutoff]
        start = cutoff - pd.Timedelta(days=730)
        scores = poisson_for_dates(history, history[history.date >= start])
        pp = np.full((len(history), 3), np.nan)
        for idx, s in scores.items():
            pp[idx] = [s[k] for k in ("probability_home_win", "probability_draw", "probability_away_win")]
        tested = CalibratedClubModel().fit(history, X, cutoff, pp)
        _, p = tested.predict(X.loc[test.index], pp[test.index])
        metrics = evaluate(test.result, ORDER[p.argmax(axis=1)], p)
        final = CalibratedClubModel().fit(history, X, history.date.max() + pd.Timedelta(days=1), pp)
        self.use_verified_bundle(history, final)
        return metrics

    def use_verified_bundle(self, history, bundle, calibrated=True):
        self.bundle = bundle
        self.model = bundle.model
        self._history = history.copy()
        self._feature_cols = bundle.feature_columns
        self.calibrated = calibrated
        self.schema_version = 3
        self._trained = True
        return self

    def _compute_sample_weights(self, df: pd.DataFrame) -> np.ndarray:
        # Simple recency decay only - no tournament-tier weighting like the WC
        # model (there's no "qualifier vs friendly" distinction for clubs;
        # league and Champions League matches are both fully competitive).
        #
        # half_life_days tuned via scripts/tune_club_recency.py: 545 days (18
        # months) beats the initial guess of 365 by a wide margin (47.9% ->
        # 50.9% accuracy). With only ~3000 matches total, decaying too
        # aggressively throws away scarce signal faster than it buys
        # relevance - a longer half-life keeps more effective sample size.
        ref_date = pd.Timestamp.now()
        days_ago = (ref_date - df["date"]).dt.days.clip(lower=0).values
        half_life_days = 545
        weights = np.exp(-np.log(2) / half_life_days * days_ago)
        return weights / weights.mean()

    def predict_match(self, home_team: str, away_team: str, is_knockout: bool = False,
                      as_of=None, market_values=None) -> dict:
        if not self._trained:
            raise RuntimeError("Model not trained. Call .train() first.")

        if self.schema_version != 3 or self.bundle is None:
            raise RuntimeError("Legacy club artifact: retrain with verified features before making new predictions")
        from .club_features_v3 import prediction_row
        from .club_backtest import rating_context
        as_of = pd.Timestamp(as_of or pd.Timestamp.now()).normalize()
        if as_of <= pd.Timestamp(self.bundle.metadata["training_end"]):
            raise ValueError("Historical prediction requires a model trained strictly before this date")
        past = self._history[self._history.date < as_of]
        X = prediction_row(past, home_team, away_team, as_of, market_values=market_values)
        for col in self._feature_cols:
            if col not in X.columns:
                X[col] = 0.0
        X = X[self._feature_cols]

        context = rating_context(past)
        poisson_pre = predict_scorelines(past, home_team, away_team, is_knockout=is_knockout,
                                         club_mode=True, rating_context=context)
        poi_proba = [
            poisson_pre["probability_home_win"],
            poisson_pre["probability_draw"],
            poisson_pre["probability_away_win"],
        ]

        raw, calibrated = self.bundle.predict(X, np.array([poi_proba]))
        blended = (calibrated if self.calibrated else raw)[0]
        total = sum(blended) or 1.0
        blended = [b / total for b in blended]

        prediction = ["H", "D", "A"][int(max(range(3), key=lambda i: blended[i]))]
        prob_home, prob_draw, prob_away = (round(float(b), 4) for b in blended)

        explanation = self._explain(home_team, away_team, X)
        target_result_probs = (prob_home, prob_draw, prob_away)
        score_pred = predict_scorelines(
            past, home_team, away_team,
            target_result_probs=target_result_probs,
            is_knockout=is_knockout,
            club_mode=True, rating_context=context,
        )
        # Most likely exact score need not have the same outcome as the
        # largest H/D/A aggregate. Keep the actual distribution's maximum.
        score_pred.pop("_all_scorelines", None)
        flow = predict_game_flow(
            score_pred["home_xg"], score_pred["away_xg"],
            home_team, away_team,
            final_score=score_pred["most_likely_score"],
        )

        return {
            "home_team": home_team,
            "away_team": away_team,
            "prediction": prediction,
            "prediction_label": RESULT_LABELS[prediction],
            "probability_home_win": prob_home,
            "probability_draw": prob_draw,
            "probability_away_win": prob_away,
            "score_prediction": score_pred,
            "game_flow": flow,
            "explanation": explanation,
            "model_version": "club_verified_v3",
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "training_end": self.bundle.metadata["training_end"],
            "market_value_policy": MARKET_VALUE_POLICY,
        }

    def _align_score_prediction(self, score_pred: dict, ensemble_result: str, top_n: int = 5) -> None:
        all_scorelines = score_pred.pop("_all_scorelines", [])
        matching = [s for s in all_scorelines if s["result"] == ensemble_result]
        if matching:
            matching.sort(key=lambda s: -s["probability"])
            score_pred["most_likely_score"] = matching[0]["score"]
            score_pred["result"] = ensemble_result
            score_pred["top_scorelines"] = [
                {"score": s["score"], "probability": s["probability"]}
                for s in matching[:top_n]
            ]

    def _explain(self, home: str, away: str, X: pd.DataFrame) -> dict:
        row = X.iloc[0]
        return {
            "form_last_10_avg_pts": {
                home: round(row.get("home_form_pts", 0), 2),
                away: round(row.get("away_form_pts", 0), 2),
            },
            "win_rate_last_10": {
                home: f"{row.get('home_form_wins', 0):.0%}",
                away: f"{row.get('away_form_wins', 0):.0%}",
            },
            "avg_goals_scored": {
                home: round(row.get("home_avg_scored", 0), 2),
                away: round(row.get("away_avg_scored", 0), 2),
            },
            "avg_goals_conceded": {
                home: round(row.get("home_avg_conceded", 0), 2),
                away: round(row.get("away_avg_conceded", 0), 2),
            },
            "clean_sheet_rate": {
                home: f"{row.get('home_clean_sheets', 0):.0%}",
                away: f"{row.get('away_clean_sheets', 0):.0%}",
            },
            "h2h_last_10": {
                f"{home} wins": f"{row.get('h2h_home_wins', 0):.0%}",
                "draws": f"{row.get('h2h_draws', 0):.0%}",
                f"{away} wins": f"{row.get('h2h_away_wins', 0):.0%}",
                "total_h2h_games": int(row.get("h2h_games", 0)),
            },
        }

    def refresh_history(self) -> int:
        """Re-read the result files so predictions see the latest matches.

        The artifact carries the history it was trained with; without this,
        form and goal features stay frozen at the training date however many
        games have been played since. The model's weights are untouched -
        a monthly refit measured no better than a frozen model - only the
        history the features are computed from moves on. Returns the number
        of matches added; refuses a history that would shrink.
        """
        from .club_features_v3 import prepare_history
        fresh = prepare_history(load_completed_matches())
        before = 0 if self._history is None else len(self._history)
        if len(fresh) < before:
            raise ValueError("Result files hold fewer matches than the model's history")
        self._history = fresh
        return len(fresh) - before

    def save(self, path: str | Path) -> None:
        joblib.dump({
            "model": self.model,
            "feature_cols": self._feature_cols,
            "history": self._history,
            "schema_version": self.schema_version,
            "bundle": self.bundle,
            "calibrated": self.calibrated,
        }, path)

    def load(self, path: str | Path) -> None:
        payload = joblib.load(path)
        self.model = payload["model"]
        self._feature_cols = payload["feature_cols"]
        self._history = payload.get("history")
        self.schema_version = payload.get("schema_version", 1)
        self.bundle = payload.get("bundle")
        self.calibrated = payload.get("calibrated", True)
        self._trained = True

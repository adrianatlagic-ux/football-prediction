from __future__ import annotations

import joblib
import pandas as pd
import numpy as np
from pathlib import Path

from .club_data_loader import load_completed_matches
from .club_feature_engineering import build_features, build_prediction_row, get_feature_columns, encode_result
from .poisson_model import predict_scorelines
from .game_flow import predict_game_flow
from .models.ensemble_model import EnsemblePredictor
from .evaluation import evaluate

RESULT_LABELS = {"H": "Home Win", "D": "Draw", "A": "Away Win"}

# Same Poisson/classifier blend ratio as the national-team model (see
# src/predictor.py) - no club-specific tuning done yet, revisit once there's
# a graded track record to tune against (scripts/tune_blend.py equivalent).
POISSON_BLEND = 0.20


class ClubFootballPredictor:
    """Same architecture as FootballPredictor (src/predictor.py) - ensemble
    classifier blended with a Poisson scoreline model - but for club football
    instead of national teams. Two real differences from the WC model:

    1. No FIFA ranking / squad market value features - those datasets only
       cover national squads, not the ~125 different clubs in
       data/club_football_results.csv. Form, goal stats, and head-to-head
       carry the whole signal here.
    2. No neutral-venue / host-nation logic - club matches are always played
       at a real home ground (Champions League included), so home advantage
       is just an ordinary model feature, not a special case to switch off.
    """

    def __init__(self, model_path: str | Path | None = None):
        self.model = EnsemblePredictor()
        self._feature_cols: list[str] = []
        self._trained = False
        self._history: pd.DataFrame | None = None

        if model_path and Path(model_path).exists():
            self.load(model_path)

    def train(self, test_size: float = 0.2) -> dict:
        history = load_completed_matches()
        history["result"] = history.apply(
            lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1
        )
        self._history = history

        print(f"Training auf {len(history):,} Klub-Spielen...")
        features = build_features(history)
        self._feature_cols = get_feature_columns(features)

        split = int(len(features) * (1 - test_size))
        train, test = features.iloc[:split], features.iloc[split:]

        sample_weight = self._compute_sample_weights(history.iloc[:split])
        self.model.fit(train[self._feature_cols], train["result"], sample_weight=sample_weight)
        self._trained = True

        y_pred = self.model.predict(test[self._feature_cols])
        y_proba = self.model.predict_proba(test[self._feature_cols])
        return evaluate(test["result"], y_pred, y_proba)

    def _compute_sample_weights(self, df: pd.DataFrame) -> np.ndarray:
        # Simple recency decay only - no tournament-tier weighting like the WC
        # model (there's no "qualifier vs friendly" distinction for clubs;
        # league and Champions League matches are both fully competitive).
        ref_date = pd.Timestamp.now()
        days_ago = (ref_date - df["date"]).dt.days.clip(lower=0).values
        half_life_days = 365
        weights = np.exp(-np.log(2) / half_life_days * days_ago)
        return weights / weights.mean()

    def predict_match(self, home_team: str, away_team: str, is_knockout: bool = False) -> dict:
        if not self._trained:
            raise RuntimeError("Model not trained. Call .train() first.")

        X = build_prediction_row(self._history, home_team, away_team)
        for col in self._feature_cols:
            if col not in X.columns:
                X[col] = 0.0
        X = X[self._feature_cols]

        clf_proba = self.model.predict_proba(X)[0]
        poisson_pre = predict_scorelines(self._history, home_team, away_team, is_knockout=is_knockout)
        poi_proba = [
            poisson_pre["probability_home_win"],
            poisson_pre["probability_draw"],
            poisson_pre["probability_away_win"],
        ]

        blended = [(1 - POISSON_BLEND) * c + POISSON_BLEND * p for c, p in zip(clf_proba, poi_proba)]
        total = sum(blended) or 1.0
        blended = [b / total for b in blended]

        prediction = ["H", "D", "A"][int(max(range(3), key=lambda i: blended[i]))]
        prob_home, prob_draw, prob_away = (round(float(b), 4) for b in blended)

        explanation = self._explain(home_team, away_team, X)
        target_result_probs = (prob_home, prob_draw, prob_away)
        score_pred = predict_scorelines(
            self._history, home_team, away_team,
            target_result_probs=target_result_probs,
            is_knockout=is_knockout,
        )
        self._align_score_prediction(score_pred, prediction)
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

    def save(self, path: str | Path) -> None:
        joblib.dump({
            "model": self.model,
            "feature_cols": self._feature_cols,
            "history": self._history,
        }, path)

    def load(self, path: str | Path) -> None:
        payload = joblib.load(path)
        self.model = payload["model"]
        self._feature_cols = payload["feature_cols"]
        self._history = payload.get("history")
        self._trained = True

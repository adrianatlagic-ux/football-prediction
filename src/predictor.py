from __future__ import annotations

import joblib
import pandas as pd
import numpy as np
from pathlib import Path

from .data_loader import load_completed_matches, load_wm2026_relevant
from .feature_engineering import build_features, build_prediction_row, get_feature_columns, encode_result, WC2026_HOST_NATIONS
from .fifa_rankings import get_ranking, get_points
from .poisson_model import predict_scorelines
from .game_flow import predict_game_flow
from .models.ensemble_model import EnsemblePredictor
from .evaluation import evaluate

RESULT_LABELS = {"H": "Home Win", "D": "Draw", "A": "Away Win"}


class FootballPredictor:
    def __init__(self, model_path: str | Path | None = None):
        self.model = EnsemblePredictor()
        self._feature_cols: list[str] = []
        self._trained = False
        self._history: pd.DataFrame | None = None

        if model_path and Path(model_path).exists():
            self.load(model_path)

    def train(self, since_year: int = 1995, test_size: float = 0.2) -> dict:
        df_raw = load_wm2026_relevant(since_year=since_year)
        df_raw["result"] = df_raw.apply(
            lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1
        )
        # History: alle Matches für Form-Berechnung der WM-Teams
        history = load_completed_matches()
        history = history[history["date"].dt.year >= since_year].reset_index(drop=True)
        history["result"] = history.apply(
            lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1
        )
        self._history = history

        print(f"Training auf {len(df_raw):,} kompetitiven WM-Team-Matches seit {since_year}...")
        features = build_features(df_raw)
        self._feature_cols = get_feature_columns(features)

        split = int(len(features) * (1 - test_size))
        train, test = features.iloc[:split], features.iloc[split:]

        sample_weight = self._compute_sample_weights(df_raw.iloc[:split])
        self.model.fit(train[self._feature_cols], train["result"], sample_weight=sample_weight)
        self._trained = True

        y_pred = self.model.predict(test[self._feature_cols])
        y_proba = self.model.predict_proba(test[self._feature_cols])
        return evaluate(test["result"], y_pred, y_proba)

    def _compute_sample_weights(self, df: pd.DataFrame) -> np.ndarray:
        ref_date = pd.Timestamp("2026-06-01")
        days_ago = (ref_date - df["date"]).dt.days.clip(lower=0).values
        half_life_days = 3 * 365
        time_w = np.exp(-np.log(2) / half_life_days * days_ago)

        year = df["date"].dt.year
        tournament = df["tournament"]
        tournament_w = np.ones(len(df))

        # WC 2026 qualification — best signal for current squad strength
        is_wc26_quali = (tournament == "FIFA World Cup qualification") & (year >= 2023)
        tournament_w[is_wc26_quali] = 5.0

        # WC 2026 group stage matches already played
        is_wc26 = (tournament == "FIFA World Cup") & (year >= 2026)
        tournament_w[is_wc26] = 5.0

        # Recent Nations League / competitive tournaments 2024-2026
        is_recent_comp = (year >= 2024) & ~is_wc26_quali & ~is_wc26 & (tournament != "Friendly")
        tournament_w[is_recent_comp] = 3.0

        # Recent friendlies 2024-2026
        is_recent_friendly = (year >= 2024) & (tournament == "Friendly")
        tournament_w[is_recent_friendly] = 2.0

        # WC 2022 — different squad but still useful reference
        is_wc22 = (tournament == "FIFA World Cup") & (year == 2022)
        tournament_w[is_wc22] = 1.5

        # WC 2018 — 8 years ago, different generation of players
        is_wc18 = (tournament == "FIFA World Cup") & (year == 2018)
        tournament_w[is_wc18] = 0.5

        # Older WC matches (before 2018)
        is_wc_old = (tournament == "FIFA World Cup") & (year < 2018)
        tournament_w[is_wc_old] = 0.2

        weights = time_w * tournament_w
        return weights / weights.mean()

    def predict_match(self, home_team: str, away_team: str, neutral: bool | None = None) -> dict:
        # WM 2026: Heimvorteil nur für Gastgeber-Nationen
        if neutral is None:
            neutral = home_team not in WC2026_HOST_NATIONS
        if not self._trained:
            raise RuntimeError("Model not trained. Call .train() first.")

        X = build_prediction_row(self._history, home_team, away_team, neutral=neutral)

        for col in self._feature_cols:
            if col not in X.columns:
                X[col] = 0.0

        X = X[self._feature_cols]
        result = self.model.predict_match(X)

        explanation = self._explain(home_team, away_team, X)
        target_result_probs = (
            result["probability_home_win"],
            result["probability_draw"],
            result["probability_away_win"],
        )
        score_pred = predict_scorelines(
            self._history, home_team, away_team,
            target_result_probs=target_result_probs,
        )
        self._align_score_prediction(score_pred, result["prediction"])
        flow = predict_game_flow(
            score_pred["home_xg"], score_pred["away_xg"],
            home_team, away_team,
            final_score=score_pred["most_likely_score"],
        )

        return {
            "home_team": home_team,
            "away_team": away_team,
            "prediction": result["prediction"],
            "prediction_label": RESULT_LABELS[result["prediction"]],
            "probability_home_win": result["probability_home_win"],
            "probability_draw": result["probability_draw"],
            "probability_away_win": result["probability_away_win"],
            "score_prediction": score_pred,
            "game_flow": flow,
            "explanation": explanation,
        }

    def _align_score_prediction(self, score_pred: dict, ensemble_result: str, top_n: int = 5) -> None:
        """Align the Poisson scoreline distribution with the ensemble's predicted result.

        The Poisson model and the ensemble classifier can disagree on H/D/A
        (different inputs/methodology). Showing "Home Win" alongside a 0:0
        "most likely score" (and a scoreline list led by 0:0) is confusing on
        the website and in the AI-generated match content. So we restrict the
        headline scoreline and the displayed "top scorelines" to those
        consistent with the ensemble's predicted outcome — the single result
        that is fed to the AI agents as "the" prediction.
        """
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
            "fifa_ranking": {
                home: get_ranking(home),
                away: get_ranking(away),
            },
            "fifa_points": {
                home: get_points(home),
                away: get_points(away),
            },
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

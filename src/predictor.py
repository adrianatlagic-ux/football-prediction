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

# Share of the pure-Poisson H/D/A blended into the classifier's prediction.
# 40% since 28 Sep 2026 (was 20%): point-in-time models for 2020-21 and
# 2024-25 scored better log-loss at 40% on every international of both years
# (1,436 matches) and on the Nations League alone (349), in both seasons
# (scripts/nl_blend_test.py). The classifier gives the home side too much and
# separates two strong teams too little - Belgium 41%, France 30% at home in
# Brussels although France led on every measure.
POISSON_BLEND = 0.40


def wc2026_neutral(home_team: str) -> bool:
    """Venue rule for WC2026 only: everyone but the three hosts plays neutral.

    Pass the result into predict_match(neutral=...) for World Cup fixtures.
    It is deliberately not the default - see predict_match.
    """
    return home_team not in WC2026_HOST_NATIONS


class FootballPredictor:
    def __init__(self, model_path: str | Path | None = None):
        self.model = EnsemblePredictor()
        self._feature_cols: list[str] = []
        self._trained = False
        self._history: pd.DataFrame | None = None

        if model_path and Path(model_path).exists():
            self.load(model_path)

    def train(self, since_year: int = 1995, test_size: float = 0.2,
              relevant_teams: set | None = None) -> dict:
        """Train on internationals since `since_year`.

        relevant_teams restricts training to matches involving at least one
        listed team. It exists for the World Cup model, which only ever had
        to rank the 48 qualified squads. It must stay None for a general
        model: 41 of the 54 Nations League entrants - Italy, Denmark, Poland,
        Wales among them - are not WC2026 participants, so that filter would
        discard most of the competition being predicted.
        """
        if relevant_teams is None:
            df_raw = load_completed_matches()
            df_raw = df_raw[df_raw["date"].dt.year >= since_year].reset_index(drop=True)
        else:
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

        scope = "Laenderspielen" if relevant_teams is None else "WM-Team-Matches"
        print(f"Training auf {len(df_raw):,} {scope} seit {since_year}...")
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
        # Anchor recency on the newest match in the data, not a fixed date.
        # The hardcoded 2026-06-01 meant every match after that point was
        # treated as equally recent, so each new Nations League round would
        # quietly stop counting as "current" the further past it we get.
        ref_date = max(df["date"].max(), pd.Timestamp.now().normalize())
        days_ago = (ref_date - df["date"]).dt.days.clip(lower=0).values
        half_life_days = 3 * 365
        time_w = np.exp(-np.log(2) / half_life_days * days_ago)

        # Competitive matches say more about current strength than friendlies,
        # where squads rotate and the result does not matter. That ordering is
        # the only claim these weights make.
        #
        # They used to single out WC2026 qualifying and WC2026 itself at 5.0,
        # which made sense while the World Cup was the thing being predicted
        # and makes none now: a 2023 qualifier would outweigh a Nations League
        # tie played last month. Recency is already handled by time_w above,
        # so competition tiering no longer carries a date rule of its own.
        # These are reasonable priors, not fitted values.
        tournament = df["tournament"]
        tournament_w = np.full(len(df), 1.0)

        is_friendly = tournament == "Friendly"
        is_major_final = tournament.isin([
            "FIFA World Cup", "UEFA Euro", "Copa América", "African Cup of Nations",
            "AFC Asian Cup", "Gold Cup",
        ])
        is_qualifier_or_league = tournament.str.contains(
            "qualification|Nations League", case=False, na=False)

        tournament_w[is_major_final.values] = 3.0
        tournament_w[is_qualifier_or_league.values] = 3.0
        tournament_w[is_friendly.values] = 1.0

        weights = time_w * tournament_w
        return weights / weights.mean()

    def predict_match(
        self, home_team: str, away_team: str, neutral: bool | None = None, is_knockout: bool = False,
        goal_uplift: float = 1.0, market_values=None,
    ) -> dict:
        # An ordinary international is played at the home team's ground, so
        # the default has to be a real home venue. This used to default to
        # `home_team not in WC2026_HOST_NATIONS`, which is right ONLY for a
        # World Cup staged entirely in three countries - every other fixture
        # (Nations League, qualifiers, friendlies) came out as neutral and
        # silently lost its home advantage. WC2026 callers now opt in via
        # wc2026_neutral() instead of the rule being the global default.
        if neutral is None:
            neutral = False
        if not self._trained:
            raise RuntimeError("Model not trained. Call .train() first.")

        X = build_prediction_row(self._history, home_team, away_team, neutral=neutral,
                                 market_values=market_values)

        for col in self._feature_cols:
            if col not in X.columns:
                X[col] = 0.0

        X = X[self._feature_cols]

        # Classifier H/D/A probabilities
        clf_proba = self.model.predict_proba(X)[0]

        # Pure Poisson H/D/A (no rescaling) - handles mismatched games far better,
        # especially draws (a 3.0 vs 0.6 xG game is almost never a draw).
        poisson_pre = predict_scorelines(self._history, home_team, away_team, is_knockout=is_knockout,
                                         goal_uplift=goal_uplift)
        poi_proba = [
            poisson_pre["probability_home_win"],
            poisson_pre["probability_draw"],
            poisson_pre["probability_away_win"],
        ]

        # Blend: classifier carries strength/form/ranking signal, Poisson carries
        # the goal-expectation shape; the share is POISSON_BLEND above.
        blended = [(1 - POISSON_BLEND) * c + POISSON_BLEND * p for c, p in zip(clf_proba, poi_proba)]
        total = sum(blended) or 1.0
        blended = [b / total for b in blended]

        prediction = ["H", "D", "A"][int(max(range(3), key=lambda i: blended[i]))]
        prob_home, prob_draw, prob_away = (round(float(b), 4) for b in blended)

        result = {
            "prediction": prediction,
            "probability_home_win": prob_home,
            "probability_draw": prob_draw,
            "probability_away_win": prob_away,
        }

        explanation = self._explain(home_team, away_team, X)
        target_result_probs = (prob_home, prob_draw, prob_away)
        score_pred = predict_scorelines(
            self._history, home_team, away_team,
            target_result_probs=target_result_probs,
            is_knockout=is_knockout,
            goal_uplift=goal_uplift,
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

    def refresh_history(self) -> int:
        """Re-read the international results so predictions see the latest
        matches, without retraining (see ClubFootballPredictor.refresh_history).
        Keeps the history's own start date. Returns the number of matches added."""
        before = 0 if self._history is None else len(self._history)
        fresh = load_completed_matches()
        if self._history is not None and len(self._history):
            fresh = fresh[fresh["date"] >= self._history["date"].min()]
        fresh = fresh.reset_index(drop=True)
        fresh["result"] = fresh.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)
        if len(fresh) < before:
            raise ValueError("Result file holds fewer matches than the model's history")
        self._history = fresh
        return len(fresh) - before

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

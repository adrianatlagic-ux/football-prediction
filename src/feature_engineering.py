from __future__ import annotations

import pandas as pd
import numpy as np
from .fifa_rankings import get_ranking, get_points, get_ranking_diff, get_points_diff
from .market_values import get_market_value_normalized, get_market_value_ratio

FORM_WINDOW = 10
H2H_WINDOW = 10

# WM 2026 Gastgeber-Nationen mit echtem Heimvorteil
WC2026_HOST_NATIONS = {"United States", "USA", "Mexico", "Canada"}


def encode_result(home_goals: float, away_goals: float) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values("date").reset_index(drop=True)
    df["result"] = df.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)
    records = []

    for idx, row in df.iterrows():
        past = df.iloc[:idx]
        is_neutral = int(row.get("neutral", False) == True or row.get("neutral") == "TRUE")
        features = {
            "match_id": idx,
            "date": row["date"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "result": row["result"],
            "is_neutral": is_neutral,
            "home_is_host": int(row["home_team"] in WC2026_HOST_NATIONS and is_neutral == 0),
            "away_is_host": int(row["away_team"] in WC2026_HOST_NATIONS and is_neutral == 0),
            "both_wm_teams": int(row.get("both_wm_teams", 1)),
        }
        features.update(_team_form(past, row["home_team"], prefix="home"))
        features.update(_team_form(past, row["away_team"], prefix="away"))
        features.update(_h2h_stats(past, row["home_team"], row["away_team"]))
        features.update(_goal_stats(past, row["home_team"], prefix="home"))
        features.update(_goal_stats(past, row["away_team"], prefix="away"))
        features["home_fifa_ranking"] = get_ranking(row["home_team"])
        features["away_fifa_ranking"] = get_ranking(row["away_team"])
        raw_rdiff = get_ranking_diff(row["home_team"], row["away_team"])
        features["ranking_diff"] = np.sign(raw_rdiff) * np.log1p(abs(raw_rdiff))
        features["home_fifa_points"] = get_points(row["home_team"])
        features["away_fifa_points"] = get_points(row["away_team"])
        raw_pdiff = get_points_diff(row["home_team"], row["away_team"])
        features["points_diff"] = np.sign(raw_pdiff) * np.log1p(abs(raw_pdiff))
        features["home_market_value"] = get_market_value_normalized(row["home_team"])
        features["away_market_value"] = get_market_value_normalized(row["away_team"])
        features["market_value_ratio"] = get_market_value_ratio(row["home_team"], row["away_team"])
        records.append(features)

    result = pd.DataFrame(records).fillna(0)
    return result


def build_prediction_row(df_history: pd.DataFrame, home_team: str, away_team: str, neutral: bool = True) -> pd.DataFrame:
    features = {
        "is_neutral": int(neutral),
        "home_is_host": int(home_team in WC2026_HOST_NATIONS and not neutral),
        "away_is_host": int(away_team in WC2026_HOST_NATIONS and not neutral),
        "both_wm_teams": 1,  # bei WM-Vorhersagen immer 1
    }
    features.update(_team_form(df_history, home_team, prefix="home"))
    features.update(_team_form(df_history, away_team, prefix="away"))
    features.update(_h2h_stats(df_history, home_team, away_team))
    features.update(_goal_stats(df_history, home_team, prefix="home"))
    features.update(_goal_stats(df_history, away_team, prefix="away"))
    features["home_fifa_ranking"] = get_ranking(home_team)
    features["away_fifa_ranking"] = get_ranking(away_team)
    raw_rdiff = get_ranking_diff(home_team, away_team)
    features["ranking_diff"] = np.sign(raw_rdiff) * np.log1p(abs(raw_rdiff))
    features["home_fifa_points"] = get_points(home_team)
    features["away_fifa_points"] = get_points(away_team)
    raw_pdiff = get_points_diff(home_team, away_team)
    features["points_diff"] = np.sign(raw_pdiff) * np.log1p(abs(raw_pdiff))
    features["home_market_value"] = get_market_value_normalized(home_team)
    features["away_market_value"] = get_market_value_normalized(away_team)
    features["market_value_ratio"] = get_market_value_ratio(home_team, away_team)
    return pd.DataFrame([features])


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    exclude = {"match_id", "date", "home_team", "away_team", "result"}
    return [c for c in df.columns if c not in exclude]


def _team_results(past: pd.DataFrame, team: str) -> pd.Series:
    home_mask = past["home_team"] == team
    away_mask = past["away_team"] == team
    home_pts = past.loc[home_mask, "result"].map({"H": 3, "D": 1, "A": 0})
    away_pts = past.loc[away_mask, "result"].map({"H": 0, "D": 1, "A": 3})
    return pd.concat([home_pts, away_pts]).sort_index()


def _decay_weights(n: int, half_life: int = 5) -> np.ndarray:
    """Exponentieller Decay: älteste Spiele zählen weniger. half_life in Spielen."""
    indices = np.arange(n)
    weights = np.exp(np.log(0.5) / half_life * (n - 1 - indices))
    return weights / weights.sum()


def _team_form(past: pd.DataFrame, team: str, prefix: str) -> dict:
    pts = _team_results(past, team).tail(FORM_WINDOW)
    if pts.empty:
        return {
            f"{prefix}_form_pts": 0.0,
            f"{prefix}_form_wins": 0.0,
            f"{prefix}_form_draws": 0.0,
            f"{prefix}_games_played": 0.0,
        }
    w = _decay_weights(len(pts))
    wins = float(np.dot((pts.values == 3).astype(float), w))
    draws = float(np.dot((pts.values == 1).astype(float), w))
    return {
        f"{prefix}_form_pts": float(np.dot(pts.values.astype(float), w)),
        f"{prefix}_form_wins": wins,
        f"{prefix}_form_draws": draws,
        f"{prefix}_games_played": len(pts),
    }


def _h2h_stats(past: pd.DataFrame, home: str, away: str) -> dict:
    mask = (
        ((past["home_team"] == home) & (past["away_team"] == away)) |
        ((past["home_team"] == away) & (past["away_team"] == home))
    )
    h2h = past.loc[mask].tail(H2H_WINDOW)
    if h2h.empty:
        return {"h2h_home_wins": 0.0, "h2h_draws": 0.0, "h2h_away_wins": 0.0, "h2h_games": 0.0}

    total = len(h2h)
    home_wins = (
        ((h2h["home_team"] == home) & (h2h["result"] == "H")).sum() +
        ((h2h["away_team"] == home) & (h2h["result"] == "A")).sum()
    )
    draws = (h2h["result"] == "D").sum()
    away_wins = total - home_wins - draws
    return {
        "h2h_home_wins": home_wins / total,
        "h2h_draws": draws / total,
        "h2h_away_wins": away_wins / total,
        "h2h_games": float(total),
    }


def _goal_stats(past: pd.DataFrame, team: str, prefix: str) -> dict:
    home_mask = past["home_team"] == team
    away_mask = past["away_team"] == team

    scored = pd.concat([
        past.loc[home_mask, "home_goals"],
        past.loc[away_mask, "away_goals"],
    ]).tail(FORM_WINDOW)

    conceded = pd.concat([
        past.loc[home_mask, "away_goals"],
        past.loc[away_mask, "home_goals"],
    ]).tail(FORM_WINDOW)

    if scored.empty:
        return {
            f"{prefix}_avg_scored": 0.0,
            f"{prefix}_avg_conceded": 0.0,
            f"{prefix}_clean_sheets": 0.0,
            f"{prefix}_avg_goal_diff": 0.0,
        }
    w = _decay_weights(len(scored))
    goal_diff = scored.values - conceded.values
    return {
        f"{prefix}_avg_scored": float(np.dot(scored.values.astype(float), w)),
        f"{prefix}_avg_conceded": float(np.dot(conceded.values.astype(float), w)),
        f"{prefix}_clean_sheets": float(np.dot((conceded.values == 0).astype(float), w)),
        f"{prefix}_avg_goal_diff": float(np.dot(goal_diff.astype(float), w)),
    }

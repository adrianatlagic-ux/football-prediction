from __future__ import annotations

import pandas as pd
import numpy as np

FORM_WINDOW = 5
H2H_WINDOW = 10


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values("date").reset_index(drop=True)
    records = []

    for idx, row in df.iterrows():
        past = df.iloc[:idx]
        features = {
            "match_id": idx,
            "date": row["date"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "result": row["result"],
        }
        features.update(_team_form(past, row["home_team"], prefix="home"))
        features.update(_team_form(past, row["away_team"], prefix="away"))
        features.update(_h2h_stats(past, row["home_team"], row["away_team"]))
        features.update(_goal_stats(past, row["home_team"], prefix="home"))
        features.update(_goal_stats(past, row["away_team"], prefix="away"))
        records.append(features)

    result = pd.DataFrame(records)
    result = result.fillna(0)
    return result


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    exclude = {"match_id", "date", "home_team", "away_team", "result"}
    return [c for c in df.columns if c not in exclude]


def _team_results(past: pd.DataFrame, team: str) -> pd.Series:
    home_mask = past["home_team"] == team
    away_mask = past["away_team"] == team
    home_pts = past.loc[home_mask, "result"].map({"H": 3, "D": 1, "A": 0})
    away_pts = past.loc[away_mask, "result"].map({"H": 0, "D": 1, "A": 3})
    return pd.concat([home_pts, away_pts]).sort_index()


def _team_form(past: pd.DataFrame, team: str, prefix: str) -> dict:
    pts = _team_results(past, team).tail(FORM_WINDOW)
    if pts.empty:
        return {f"{prefix}_form_pts": 0.0, f"{prefix}_form_wins": 0.0, f"{prefix}_form_draws": 0.0}
    wins = (pts == 3).sum()
    draws = (pts == 1).sum()
    return {
        f"{prefix}_form_pts": pts.mean(),
        f"{prefix}_form_wins": wins / len(pts),
        f"{prefix}_form_draws": draws / len(pts),
    }


def _h2h_stats(past: pd.DataFrame, home: str, away: str) -> dict:
    mask = (
        ((past["home_team"] == home) & (past["away_team"] == away)) |
        ((past["home_team"] == away) & (past["away_team"] == home))
    )
    h2h = past.loc[mask].tail(H2H_WINDOW)
    if h2h.empty:
        return {"h2h_home_wins": 0.0, "h2h_draws": 0.0, "h2h_away_wins": 0.0}

    total = len(h2h)
    home_wins = ((h2h["home_team"] == home) & (h2h["result"] == "H")).sum() + \
                ((h2h["away_team"] == home) & (h2h["result"] == "A")).sum()
    draws = (h2h["result"] == "D").sum()
    away_wins = total - home_wins - draws
    return {
        "h2h_home_wins": home_wins / total,
        "h2h_draws": draws / total,
        "h2h_away_wins": away_wins / total,
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
        return {f"{prefix}_avg_scored": 0.0, f"{prefix}_avg_conceded": 0.0, f"{prefix}_clean_sheets": 0.0}
    return {
        f"{prefix}_avg_scored": scored.mean(),
        f"{prefix}_avg_conceded": conceded.mean(),
        f"{prefix}_clean_sheets": (conceded == 0).mean(),
    }

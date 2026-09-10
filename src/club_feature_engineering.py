from __future__ import annotations

import pandas as pd
import numpy as np

# Form/H2H/goal-stat helpers are club-vs-country agnostic (just rolling stats
# over a team's own match history), so they're reused as-is from the WC
# module. Only the club-specific feature set below differs: no FIFA
# ranking/market value/host-nation bonus, since none of that exists for
# clubs - real home advantage (not a tournament host bonus) is the only
# home/away signal available.
from .feature_engineering import (
    encode_result, _team_form, _h2h_stats, _goal_stats,
)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values("date").reset_index(drop=True)
    df["result"] = df.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)
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

    return pd.DataFrame(records).fillna(0)


def build_prediction_row(df_history: pd.DataFrame, home_team: str, away_team: str) -> pd.DataFrame:
    features = {}
    features.update(_team_form(df_history, home_team, prefix="home"))
    features.update(_team_form(df_history, away_team, prefix="away"))
    features.update(_h2h_stats(df_history, home_team, away_team))
    features.update(_goal_stats(df_history, home_team, prefix="home"))
    features.update(_goal_stats(df_history, away_team, prefix="away"))
    return pd.DataFrame([features])


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    exclude = {"match_id", "date", "home_team", "away_team", "result"}
    return [c for c in df.columns if c not in exclude]

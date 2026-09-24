"""Public club feature API sharing V3 point-in-time rules.

Old classifiers need retraining. Seasonal labels do not prove availability.
"""
import pandas as pd
from .feature_engineering import encode_result
from .club_features_v3 import prepare_history, build_features as dated_features, prediction_row


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    history = prepare_history(df)
    metadata = history[["date", "home_team", "away_team", "result"]].copy()
    metadata.insert(0, "match_id", history.index)
    return pd.concat([metadata, dated_features(history)], axis=1)


def build_prediction_row(df_history, home_team, away_team, as_of=None):
    return prediction_row(df_history, home_team, away_team,
                          as_of if as_of is not None else pd.Timestamp.now().normalize())


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    exclude = {"match_id", "date", "home_team", "away_team", "result"}
    return [c for c in df.columns if c not in exclude]

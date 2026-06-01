import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd
from src.feature_engineering import build_features, get_feature_columns


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=20, freq="7D"),
        "home_team": ["Bayern", "Dortmund"] * 10,
        "away_team": ["Dortmund", "Bayern"] * 10,
        "home_goals": [2, 1, 3, 0, 1, 2, 2, 1, 3, 0, 1, 2, 2, 1, 3, 0, 1, 2, 2, 1],
        "away_goals": [1, 2, 1, 1, 0, 1, 0, 2, 1, 0, 1, 1, 0, 2, 1, 1, 0, 1, 0, 3],
        "result": ["H", "A", "H", "D", "H", "H", "H", "A", "H", "D",
                   "H", "H", "H", "A", "H", "D", "H", "H", "H", "A"],
    })


def test_build_features_shape(sample_df):
    features = build_features(sample_df)
    assert len(features) == len(sample_df)


def test_feature_columns_no_leakage(sample_df):
    features = build_features(sample_df)
    cols = get_feature_columns(features)
    assert not {"result", "date", "home_team", "away_team", "match_id"}.intersection(set(cols))


def test_no_nans_after_build(sample_df):
    features = build_features(sample_df)
    cols = get_feature_columns(features)
    assert features[cols].isnull().sum().sum() == 0


def test_h2h_ratios_sum_to_one(sample_df):
    features = build_features(sample_df)
    s = features[["h2h_home_wins", "h2h_draws", "h2h_away_wins"]].sum(axis=1)
    non_zero = s[s > 0]
    assert (non_zero - 1.0).abs().max() < 1e-9

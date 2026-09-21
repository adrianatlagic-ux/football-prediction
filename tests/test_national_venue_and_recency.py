"""Guards for the national-team model outside the World Cup context.

Both behaviours below were tuned for WC2026 and were silently wrong for any
other competition (Nations League, qualifiers, friendlies).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.feature_engineering import build_prediction_row, encode_result
from src.predictor import FootballPredictor, wc2026_neutral


def history(n=60):
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="7D"),
        "home_team": ["Germany", "Italy", "Spain"] * (n // 3),
        "away_team": ["Italy", "Spain", "Germany"] * (n // 3),
        "home_goals": [2, 1, 0] * (n // 3),
        "away_goals": [1, 1, 2] * (n // 3),
        "tournament": ["UEFA Nations League"] * n,
        "neutral": [False] * n,
    }).assign(result=lambda d: [encode_result(h, a) for h, a in zip(d.home_goals, d.away_goals)])


def test_ordinary_international_keeps_home_advantage():
    """A Nations League home tie is not played at a neutral venue."""
    df = history()
    home = build_prediction_row(df, "Germany", "Italy", neutral=False)
    neutral = build_prediction_row(df, "Germany", "Italy", neutral=True)
    assert not home.equals(neutral), "neutral flag must change the feature row"
    # The old default derived neutrality from the WC host list, which makes
    # every non-host home tie neutral - the bug this pins down.
    assert wc2026_neutral("Germany") is True
    assert wc2026_neutral("Mexico") is False


def test_world_cup_rule_still_available_explicitly():
    assert wc2026_neutral("United States") is False
    assert wc2026_neutral("Canada") is False
    assert wc2026_neutral("Brazil") is True


def test_recency_anchors_on_the_newest_match_not_a_fixed_date():
    """Weights must not freeze at a hardcoded reference date."""
    p = FootballPredictor()
    old = history()
    new = old.copy()
    new["date"] = new["date"] + pd.Timedelta(days=365 * 3)

    w_old = p._compute_sample_weights(old)
    w_new = p._compute_sample_weights(new)
    # Same shape of data, shifted in time: normalized weights are identical
    # because recency is measured relative to the data itself.
    np.testing.assert_allclose(w_old, w_new, rtol=1e-9)
    # And within one dataset, newer matches still outweigh older ones.
    assert w_old[-1] > w_old[0]

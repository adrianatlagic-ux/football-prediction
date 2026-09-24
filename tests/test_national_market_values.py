"""The national market-value table, and what a missing entry may mean.

A Nations League round exposed the bug these cover: the table held only the
48 World Cup 2026 participants, so eleven of sixteen teams had no entry, and
a miss returned 0 with a hard-coded 2.0 ratio. Denmark was worth nothing and
Norway twice as strong.
"""
import csv
from pathlib import Path

import pandas as pd
import pytest

from src.feature_engineering import build_prediction_row
from src.market_values import (
    MARKET_VALUES, VALUES, get_market_value_normalized, get_market_value_ratio,
    has_market_value)

CSV = Path(__file__).resolve().parents[1] / "data" / "national_market_values.csv"
# Everyone who played the 2026-09-24 Nations League round.
MATCHDAY = ["Andorra", "Malta", "Austria", "Israel", "Kosovo", "Republic of Ireland",
            "Liechtenstein", "Lithuania", "Netherlands", "Germany", "Norway",
            "Denmark", "Portugal", "Wales", "Serbia", "Greece"]


@pytest.mark.parametrize("team", MATCHDAY)
def test_every_nations_league_team_has_a_value(team):
    assert has_market_value(team), f"{team} would fall back to the 0 placeholder"
    assert get_market_value_normalized(team) > 0


def test_unknown_team_gets_a_neutral_ratio_not_a_claim():
    """The old code answered 2.0 here - a confident claim in the wrong direction."""
    assert get_market_value_ratio("Germany", "Nowhereia") == 1.0
    assert get_market_value_ratio("Nowhereia", "Germany") == 1.0
    assert get_market_value_ratio("Nowhereia", "Elsewherea") == 1.0


def test_known_pairs_still_compare_by_value():
    assert get_market_value_ratio("Germany", "Andorra") > 10
    assert get_market_value_ratio("Andorra", "Germany") < 0.1


def test_missing_flag_marks_the_placeholder():
    history = pd.DataFrame([{"date": pd.Timestamp("2026-06-01"),
                             "home_team": "Germany", "away_team": "Netherlands",
                             "home_goals": 1, "away_goals": 1, "result": "draw"}])
    known = build_prediction_row(history, "Germany", "Netherlands")
    unknown = build_prediction_row(history, "Germany", "Nowhereia")
    assert known["market_value_missing"].iloc[0] == 0
    assert unknown["market_value_missing"].iloc[0] == 1


def test_csv_overlays_the_hand_written_table():
    """The scraped file wins, so refetching actually changes what the model sees."""
    rows = {r["team"]: int(r["market_value_total_eur"]) for r in csv.DictReader(CSV.open())}
    both = set(rows) & set(MARKET_VALUES)
    assert both, "no overlap - the alias mapping is probably broken"
    for team in both:
        assert VALUES[team] == rows[team]


def test_csv_values_are_plausible():
    rows = list(csv.DictReader(CSV.open()))
    assert len(rows) >= 50, "expected all UEFA nations"
    for row in rows:
        value = int(row["market_value_total_eur"])
        # Liechtenstein sits near 600k; England near 1.8bn.
        assert 1e5 < value < 5e9, f"{row['team']} = {value}"

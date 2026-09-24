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


def _history():
    return pd.DataFrame([{"date": pd.Timestamp("2026-06-01"),
                          "home_team": "Germany", "away_team": "Netherlands",
                          "home_goals": 1, "away_goals": 1, "result": "draw"}])


def test_a_named_squad_replaces_the_stored_value_for_one_match():
    """The correction the whole squad pipeline exists to make.

    A nation's stored value is its standing strength. When the squad actually
    named is worth less, that stored number describes a team which is not
    playing, and the model should be told so for this fixture only.
    """
    weaker = build_prediction_row(_history(), "Germany", "Netherlands",
                                  market_values={"Germany": 400_000_000})
    stored = build_prediction_row(_history(), "Germany", "Netherlands")
    assert weaker["home_market_value"].iloc[0] < stored["home_market_value"].iloc[0]
    assert weaker["market_value_ratio"].iloc[0] < stored["market_value_ratio"].iloc[0]
    # The opponent was not overridden, so its stored value must be untouched.
    assert weaker["away_market_value"].iloc[0] == stored["away_market_value"].iloc[0]


def test_an_override_equal_to_the_stored_value_changes_nothing():
    """Guards the no-op case: for national teams both come from the same page."""
    same = build_prediction_row(_history(), "Germany", "Netherlands",
                                market_values={"Germany": VALUES["Germany"]})
    stored = build_prediction_row(_history(), "Germany", "Netherlands")
    for column in ("home_market_value", "away_market_value", "market_value_ratio"):
        assert same[column].iloc[0] == stored[column].iloc[0]


def test_an_override_can_supply_a_team_we_have_no_stored_value_for():
    """A squad we priced today beats having no number at all."""
    known = build_prediction_row(_history(), "Germany", "Nowhereia",
                                 market_values={"Nowhereia": 200_000_000})
    assert known["market_value_missing"].iloc[0] == 0
    assert known["away_market_value"].iloc[0] > 0
    assert known["market_value_ratio"].iloc[0] != 1.0

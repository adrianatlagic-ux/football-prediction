"""Dated squad market values for German clubs (Bundesliga + 2. Bundesliga),
one snapshot per season instead of the single current-season snapshot in
club_market_values.py. Built for the V2 feature pipeline specifically, to
close the look-ahead leak that using today's values for old matches creates.

Coverage is Germany-only for now (data/club_market_values_history.csv, via
scripts/fetch_bundesliga_market_values_history.py) - non-German clubs fall
back to 0, the same "uncovered team" convention already used by
club_market_values.py and src/market_values.py.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

_DATA_PATH = Path(__file__).parent.parent / "data" / "club_market_values_history.csv"


@lru_cache(maxsize=1)
def _load():
    df = pd.read_csv(_DATA_PATH)
    lookup = {(row.team, int(row.season_start_year)): float(row.market_value) for row in df.itertuples()}
    max_value = float(df["market_value"].max())
    return lookup, max_value


def _season_for_date(as_of) -> int:
    # Bundesliga seasons start mid-August; a date from July onward belongs
    # to the season starting that year, otherwise to the one that started
    # the previous year.
    ts = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now()
    return ts.year if ts.month >= 7 else ts.year - 1


def get_market_value(team: str, as_of=None) -> float:
    lookup, _ = _load()
    season = _season_for_date(as_of)
    # Walk back a few seasons if this exact one is missing (e.g. a club with
    # a gap year in the scraped range) rather than silently falling to 0
    # when nearby real data exists.
    for s in range(season, season - 5, -1):
        val = lookup.get((team, s))
        if val is not None:
            return val
    return 0.0


def get_market_value_normalized(team: str, as_of=None) -> float:
    _, max_value = _load()
    return get_market_value(team, as_of) / max_value


def get_market_value_ratio(home: str, away: str, as_of=None) -> float:
    h = get_market_value(home, as_of)
    a = get_market_value(away, as_of)
    if h == 0 and a == 0:
        return 1.0
    if a == 0:
        return 2.0
    if h == 0:
        return 0.5
    return h / a

from __future__ import annotations

import pandas as pd
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "international_results.csv"


def load_all_matches() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
    df["home_goals"] = pd.to_numeric(df["home_goals"], errors="coerce")
    df["away_goals"] = pd.to_numeric(df["away_goals"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def load_completed_matches() -> pd.DataFrame:
    df = load_all_matches()
    return df.dropna(subset=["home_goals", "away_goals"]).reset_index(drop=True)


def load_wc2026_fixtures() -> pd.DataFrame:
    df = load_all_matches()
    wc = df[df["tournament"] == "FIFA World Cup"].copy()
    fixtures = wc[wc["home_goals"].isna()].reset_index(drop=True)
    return fixtures


def load_wc_matches_only() -> pd.DataFrame:
    df = load_completed_matches()
    return df[df["tournament"] == "FIFA World Cup"].reset_index(drop=True)

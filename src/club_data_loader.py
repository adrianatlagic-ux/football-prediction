from __future__ import annotations

import pandas as pd
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "club_football_results.csv"


def load_completed_matches() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
    df["home_goals"] = pd.to_numeric(df["home_goals"], errors="coerce")
    df["away_goals"] = pd.to_numeric(df["away_goals"], errors="coerce")
    return df.dropna(subset=["home_goals", "away_goals"]).sort_values("date").reset_index(drop=True)

from __future__ import annotations

import pandas as pd
from pathlib import Path

DATA_PATH   = Path(__file__).parent.parent / "data" / "international_results.csv"
RECENT_PATH = Path(__file__).parent.parent / "data" / "recent_international_2024_2026.csv"

# Alle 48 WM 2026 Teilnehmer
WM2026_TEAMS = {
    "Mexico", "South Africa", "South Korea", "Czech Republic",
    "Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland",
    "Brazil", "Morocco", "Haiti", "Scotland",
    "United States", "Paraguay", "Australia", "Turkey",
    "Germany", "Curaçao", "Ivory Coast", "Ecuador",
    "Netherlands", "Japan", "Sweden", "Tunisia",
    "Belgium", "Egypt", "Iran", "New Zealand",
    "Spain", "Cape Verde", "Saudi Arabia", "Uruguay",
    "France", "Senegal", "Iraq", "Norway",
    "Argentina", "Algeria", "Austria", "Jordan",
    "Portugal", "DR Congo", "Uzbekistan", "Colombia",
    "England", "Croatia", "Ghana", "Panama",
}

FRIENDLY_TOURNAMENTS = {"Friendly", "Friendly international"}


def load_all_matches() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
    df["home_goals"] = pd.to_numeric(df["home_goals"], errors="coerce")
    df["away_goals"] = pd.to_numeric(df["away_goals"], errors="coerce")

    return df.sort_values("date").reset_index(drop=True)


def load_completed_matches() -> pd.DataFrame:
    df = load_all_matches()
    return df.dropna(subset=["home_goals", "away_goals"]).reset_index(drop=True)


def load_wm2026_relevant(since_year: int = 1995) -> pd.DataFrame:
    """
    Matches wo mind. EIN Team ein WM-2026-Teilnehmer ist (inkl. Freundschaftsspiele,
    fuer eine groessere Datengrundlage gerade bei kleineren Nationen).
    """
    df = load_completed_matches()
    df = df[df["date"].dt.year >= since_year]
    df = df[df["home_team"].isin(WM2026_TEAMS) | df["away_team"].isin(WM2026_TEAMS)]
    # Feature: spielen beide Teams bei der WM mit?
    df = df.copy()
    df["both_wm_teams"] = (
        df["home_team"].isin(WM2026_TEAMS) & df["away_team"].isin(WM2026_TEAMS)
    ).astype(int)
    df["is_friendly"] = df["tournament"].isin(FRIENDLY_TOURNAMENTS).astype(int)
    return df.reset_index(drop=True)


def load_wc2026_fixtures() -> pd.DataFrame:
    df = load_all_matches()
    wc = df[df["tournament"] == "FIFA World Cup"].copy()
    fixtures = wc[wc["home_goals"].isna()].reset_index(drop=True)
    return fixtures


def load_wc_matches_only() -> pd.DataFrame:
    df = load_completed_matches()
    return df[df["tournament"] == "FIFA World Cup"].reset_index(drop=True)

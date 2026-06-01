from __future__ import annotations

import os
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

FOOTBALL_DATA_API = "https://api.football-data.org/v4"
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

REQUIRED_COLUMNS = ["date", "home_team", "away_team", "home_goals", "away_goals"]


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    _validate(df)
    return _normalize(df)


def load_from_api(competition: str = "PL", seasons: list[int] | None = None) -> pd.DataFrame:
    """
    Fetch matches from football-data.org.
    Requires FOOTBALL_DATA_API_KEY env variable.
    competition: PL, BL1, SA, PD, FL1
    """
    if not API_KEY:
        raise EnvironmentError("FOOTBALL_DATA_API_KEY not set")

    headers = {"X-Auth-Token": API_KEY}
    seasons = seasons or [datetime.now().year - 1]
    frames: list[pd.DataFrame] = []

    for season in seasons:
        url = f"{FOOTBALL_DATA_API}/competitions/{competition}/matches"
        resp = requests.get(url, headers=headers, params={"season": season}, timeout=15)
        resp.raise_for_status()
        frames.append(_parse_api_response(resp.json()))

    df = pd.concat(frames, ignore_index=True)
    _validate(df)
    return _normalize(df)


def load_sample_data() -> pd.DataFrame:
    sample = Path(__file__).parent.parent / "data" / "sample_matches.csv"
    return load_csv(sample)


def _parse_api_response(data: dict) -> pd.DataFrame:
    rows = []
    for match in data.get("matches", []):
        score = match.get("score", {}).get("fullTime", {})
        rows.append({
            "date": match["utcDate"][:10],
            "home_team": match["homeTeam"]["shortName"],
            "away_team": match["awayTeam"]["shortName"],
            "home_goals": score.get("home"),
            "away_goals": score.get("away"),
            "competition": data.get("competition", {}).get("code", ""),
            "season": match.get("season", {}).get("startDate", "")[:4],
            "matchday": match.get("matchday"),
            "status": match.get("status"),
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _validate(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["home_goals"] = pd.to_numeric(df["home_goals"], errors="coerce")
    df["away_goals"] = pd.to_numeric(df["away_goals"], errors="coerce")
    df = df.dropna(subset=["home_goals", "away_goals"])
    df["result"] = df.apply(_encode_result, axis=1)
    return df.sort_values("date").reset_index(drop=True)


def _encode_result(row: pd.Series) -> str:
    if row["home_goals"] > row["away_goals"]:
        return "H"
    if row["home_goals"] < row["away_goals"]:
        return "A"
    return "D"

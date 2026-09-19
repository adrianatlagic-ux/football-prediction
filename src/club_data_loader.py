"""Load normalized results WITH competition/season provenance from raw files."""
from pathlib import Path
import pandas as pd

RAW_PATH = Path(__file__).resolve().parents[1] / "data" / "club_raw"
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "club_football_results.csv"
COMPETITIONS = {"bundesliga": "bundesliga", "bundesliga2": "bundesliga2",
                "cl": "champions_league", "pl": "premier_league"}


def load_completed_matches(raw_path=RAW_PATH):
    from scripts.build_club_training_data import _canon
    frames = []
    for path in sorted(Path(raw_path).glob("*.csv")):
        prefix, season = path.stem.rsplit("_", 1)
        if prefix not in COMPETITIONS:
            raise ValueError(f"Unknown source competition: {path.name}")
        frame = pd.read_csv(path, parse_dates=["date"])
        frame = frame.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
        for c in ("home_team", "away_team"):
            frame[c] = frame[c].map(_canon)
        for c in ("home_goals", "away_goals"):
            frame[c] = pd.to_numeric(frame[c], errors="raise")
            if ((frame[c] < 0) | (frame[c] % 1 != 0) | frame[c].isna()).any():
                raise ValueError(f"Invalid scores in {path.name}")
        frame["competition"] = COMPETITIONS[prefix]
        frame["season"] = season
        frame["source_file"] = path.name
        frames.append(frame)
    if not frames:
        raise ValueError("No club raw data found")
    df = pd.concat(frames, ignore_index=True)
    keys = ["date", "home_team", "away_team"]
    if df.duplicated(keys).any():
        raise ValueError("Duplicate match identity in source data; reconcile before training")
    return df.sort_values(keys, kind="stable").reset_index(drop=True)

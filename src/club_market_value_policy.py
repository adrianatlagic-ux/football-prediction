"""Point-in-time values. Season-only data is NOT verified pre-match evidence.

verified_only: only rows with available_at + source are eligible.
lagged_season: sensitivity analysis assuming previous seasons' values were
available by July 1 of the following year. This assumption is NOT proven.
"""
from pathlib import Path
import numpy as np
import pandas as pd

PATH = Path(__file__).resolve().parents[1] / "data" / "club_market_values_history.csv"


class MarketValueHistory:
    def __init__(self, path=PATH):
        self.frame = pd.read_csv(path)
        self.frame["available_at"] = pd.to_datetime(self.frame.get("available_at", pd.Series(dtype=str)), utc=True, errors="coerce")
        self.frame["source"] = self.frame.get("source", "")
        self.by_team = {t: g for t, g in self.frame.groupby("team")}

    def value(self, team, as_of, policy="verified_only"):
        if policy not in ("verified_only", "lagged_season", "none"):
            raise ValueError(f"Unknown market value policy {policy}")
        if policy == "none" or team not in self.by_team:
            return None
        cutoff = pd.Timestamp(as_of)
        cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
        rows = self.by_team[team]
        valid = rows[rows.available_at.notna() & (rows.available_at < cutoff) & rows.source.fillna("").ne("")]
        if not valid.empty:
            return float(valid.sort_values("available_at").iloc[-1].market_value)
        if policy == "verified_only":
            return None
        season = cutoff.year if cutoff.month >= 7 else cutoff.year - 1
        past = rows[(rows.season_start_year < season) & (rows.season_start_year >= season - 4)]
        return None if past.empty else float(past.sort_values("season_start_year").iloc[-1].market_value)

    def features(self, home, away, as_of, policy="verified_only"):
        h, a = self.value(home, as_of, policy), self.value(away, as_of, policy)
        # Fixed denominator; never a maximum computed using future seasons.
        return {"home_market_value": (h or 0) / 1e9, "away_market_value": (a or 0) / 1e9,
                "market_value_ratio": h / a if h and a else 1.0,
                "home_market_value_missing": float(h is None), "away_market_value_missing": float(a is None)}

    def audit(self):
        dated = self.frame.available_at.notna() & self.frame.source.fillna("").ne("")
        return {"rows": len(self.frame), "teams": self.frame.team.nunique(),
                "verified_rows": int(dated.sum()), "season_only_rows": int((~dated).sum()),
                "default_policy": "verified_only", "coverage": "German clubs only",
                "lagged_season": "Sensitivity analysis only: historical availability not demonstrated"}

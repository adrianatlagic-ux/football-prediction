"""Point-in-time market values under an explicit availability assumption.

verified_only:  only rows carrying available_at + source. Our history has
                none, so this yields no values at all.
lagged_season:  the previous season's value, assumed known by 1 July.
current_season: the current season's value, assumed published at season
                start. This is the production default.

Why current_season is the default despite being the stronger assumption:
it is the only policy under which training and live prediction use the same
rule. At prediction time the newest figure available is the current season's,
so a model trained on lagged values would either have to be served stale
values or be fed a feature it never learned - train/serve skew either way.
A walk-forward comparison (scripts/compare_market_value_policies.py) also
measured it best on Bundesliga fixtures: log loss 0.9884 vs 1.0029 for no
values at all, paired z = -3.53 over 1224 matches.

The open risk, stated plainly: we cannot demonstrate WHEN a season's figure
was published. If a value labelled "2023" is really a May 2024 snapshot, an
October 2023 training row sees the future. The measured advantage over
lagged_season is small (0.0074 log loss), which is more consistent with
genuinely fresher information than with end-of-season leakage - but that is
an inference, not evidence. The durable fix is to record today's values with
today's timestamp from now on, so verified_only becomes usable over time.

Coverage is German clubs only. In Champions League fixtures, where most
clubs therefore have no value at all, market values measured slightly WORSE
than omitting them (paired z = +1.22, not significant).
"""
from pathlib import Path
import numpy as np
import pandas as pd

PATH = Path(__file__).resolve().parents[1] / "data" / "club_market_values_history.csv"

DEFAULT_POLICY = "current_season"


class MarketValueHistory:
    def __init__(self, path=PATH):
        self.frame = pd.read_csv(path)
        self.frame["available_at"] = pd.to_datetime(self.frame.get("available_at", pd.Series(dtype=str)), utc=True, errors="coerce")
        self.frame["source"] = self.frame.get("source", "")
        self.by_team = {t: g for t, g in self.frame.groupby("team")}

    def value(self, team, as_of, policy=DEFAULT_POLICY):
        if policy not in ("verified_only", "lagged_season", "current_season", "none"):
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
        # current_season assumes a season's value was already published when
        # that season kicked off. That is the more aggressive assumption: a
        # Transfermarkt figure labelled "2023" may equally be a May 2024
        # snapshot, in which case an October 2023 match would be scored with
        # information from months later. Kept as a comparable policy so the
        # cost of that assumption can be measured rather than argued about.
        upper = season if policy == "current_season" else season - 1
        # The season fallback covers UNDATED legacy rows only. A row that
        # carries a publication date has already been judged above: if that
        # date is in the future relative to the query, the value was not
        # public yet and must stay invisible. Letting the season window pick
        # it up anyway would reintroduce exactly the look-ahead this class
        # exists to prevent (tests/test_profit_pipeline.py covers this).
        undated = rows[rows.available_at.isna() | rows.source.fillna("").eq("")]
        past = undated[(undated.season_start_year <= upper) & (undated.season_start_year >= upper - 3)]
        return None if past.empty else float(past.sort_values("season_start_year").iloc[-1].market_value)

    def features(self, home, away, as_of, policy=DEFAULT_POLICY, override=None):
        """Market-value features, optionally for one specific fixture.

        override carries the squad available for this match - the standing
        roster minus whoever is injured or suspended for it. The stored value
        describes a club at full strength, which is what history should be
        trained on and not what an eleven missing its two most valuable
        players is worth on the night.
        """
        h, a = self.value(home, as_of, policy), self.value(away, as_of, policy)
        if override:
            h, a = override.get(home, h), override.get(away, a)
        # Fixed denominator; never a maximum computed using future seasons.
        return {"home_market_value": (h or 0) / 1e9, "away_market_value": (a or 0) / 1e9,
                "market_value_ratio": h / a if h and a else 1.0,
                "home_market_value_missing": float(h is None), "away_market_value_missing": float(a is None)}

    def audit(self):
        dated = self.frame.available_at.notna() & self.frame.source.fillna("").ne("")
        return {"rows": len(self.frame), "teams": self.frame.team.nunique(),
                "verified_rows": int(dated.sum()), "season_only_rows": int((~dated).sum()),
                "default_policy": DEFAULT_POLICY, "coverage": "German clubs only",
                "lagged_season": "Sensitivity analysis only: historical availability not demonstrated"}

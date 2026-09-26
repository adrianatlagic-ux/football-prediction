"""Bring the result files up to date from ESPN.

Both models keep the match history they were trained with inside their
artifact, and the files that history comes from were only ever updated by
hand: the club files stopped at 13 September, the international one at the
end of June. A prediction for Dortmund on the 21st therefore knew nothing of
Dortmund's games on the 12th and 16th. Retraining is not what fixes that - a
monthly refit measured no better than a frozen model
(data/model_reports/retraining_v3) - the form features simply have to be
computed from a history that includes those games. So this appends finished
matches to the files, and the predictors re-read them (refresh_history).

Only regulation-time results are written (see parse_event), existing rows are
never changed, and a match already present is skipped, so running this every
day is safe.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLUB_RAW = ROOT / "data" / "club_raw"
# ESPN league slug -> the club file prefix src/club_data_loader.py reads.
CLUB_LEAGUES = {"ger.1": "bundesliga", "uefa.champions": "cl"}
NATIONAL_LEAGUES = ("uefa.nations",)
# A redeploy resets the server's files to the repository's, so the daily run
# looks back far enough to refill whatever the image lacks.
LOOKBACK_DAYS = 30


def season_label(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _fetch_day(league: str, day: date) -> list:
    import json
    import urllib.request
    url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}"
           f"/scoreboard?dates={day.strftime('%Y%m%d')}&limit=100")
    # No User-Agent: ESPN refuses a spoofed browser one (see api/app.py).
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read()).get("events", [])


def update_club_results(today: Optional[date] = None, days: int = LOOKBACK_DAYS) -> list:
    """Append finished Bundesliga and Champions League matches; returns them."""
    from scripts.build_club_training_data import _canon
    from scripts.fetch_national_results import parse_event
    today = today or date.today()
    added, failed = [], []
    for league, prefix in CLUB_LEAGUES.items():
        rows, errors = [], 0
        for offset in range(days, -1, -1):
            try:
                events = _fetch_day(league, today - timedelta(days=offset))
            except Exception:
                errors += 1
                continue
            rows += [r for r in (parse_event(e, prefix) for e in events) if r]
        # One missing day is tolerated (ESPN has gaps); a competition whose
        # every day failed must not pass as "no new results".
        if errors == days + 1:
            failed.append(league)
        for row in rows:
            path = CLUB_RAW / f"{prefix}_{season_label(date.fromisoformat(row['date']))}.csv"
            have = set()
            if path.exists():
                existing = pd.read_csv(path)
                have = {(str(r.date)[:10], _canon(r.home_team), _canon(r.away_team))
                        for r in existing.itertuples()}
            key = (row["date"], _canon(row["home_team"]), _canon(row["away_team"]))
            if key in have:
                continue
            new = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                if new:
                    writer.writerow(["date", "home_team", "away_team", "home_score", "away_score"])
                writer.writerow([row["date"], row["home_team"], row["away_team"],
                                 row["home_score"], row["away_score"]])
            added.append({**row, "file": path.name})
    if failed:
        raise RuntimeError(f"ESPN unreachable for {', '.join(failed)}; added {len(added)} other results")
    return added


def update_national_results(seasons=None) -> list:
    """Append finished Nations League matches to the international file."""
    from scripts.fetch_national_results import CSV_PATH, LEAGUES, fetch_season, parse_event
    seasons = seasons or [date.today().year]
    existing = pd.read_csv(CSV_PATH)
    have = {(r.date, r.home_team, r.away_team) for r in existing.itertuples()}
    new, failed = [], []
    for league in NATIONAL_LEAGUES:
        for season in seasons:
            try:
                events = fetch_season(league, season)
            except Exception as exc:
                failed.append(f"{league} {season}: {type(exc).__name__}")
                continue
            for row in (parse_event(e, LEAGUES[league]) for e in events):
                if row and (row["date"], row["home_team"], row["away_team"]) not in have:
                    have.add((row["date"], row["home_team"], row["away_team"]))
                    new.append(row)
    if new:
        combined = pd.concat([existing, pd.DataFrame(new)], ignore_index=True)
        combined = combined.sort_values("date", kind="stable")
        combined.to_csv(CSV_PATH, index=False)
    if failed:
        raise RuntimeError(f"ESPN unreachable: {'; '.join(failed)}; added {len(new)} results")
    return new

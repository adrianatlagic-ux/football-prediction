"""Append completed national-team results from ESPN to the training CSV.

The existing scripts/update_training_data.py only fills scores into rows
that were pre-created for the WC2026 schedule; it cannot add fixtures the
CSV has never seen. This script does the missing half: it pulls finished
matches for a competition and appends the ones we do not already have, so
the national-team model can keep learning after the World Cup.

    python3 scripts/fetch_national_results.py                    # dry run
    python3 scripts/fetch_national_results.py --write
    python3 scripts/fetch_national_results.py --league uefa.euroq --seasons 2027

Only completed matches are written, and only at their regulation score -
ESPN reports an aggregate for two-legged ties and a shootout winner for
knockouts, neither of which belongs in a result row. Existing rows are
never modified: a date/teams collision is skipped and reported, so a
mistaken second source cannot silently rewrite history.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "international_results.csv"

# ESPN league slug -> the tournament label already used in the CSV. Writing a
# new label for an existing competition would split it into two categories
# that the sample weighting then treats differently, so these must match the
# existing spelling exactly.
LEAGUES = {
    "uefa.nations": "UEFA Nations League",
    "concacaf.nations.league": "CONCACAF Nations League",
    "fifa.worldq.uefa": "FIFA World Cup qualification",
}

# ESPN spellings that differ from the CSV's. Kept in sync with the same map
# in api/app.py.
NAME_MAP = {
    "Czechia": "Czech Republic",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Türkiye": "Turkey",
    "Curaçao": "Curacao",
    "Congo DR": "DR Congo",
    "USA": "United States",
}


def team_name(raw: str) -> str:
    return NAME_MAP.get(raw, raw)


def fetch_season(league: str, season: int) -> list[dict]:
    url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}"
           f"/scoreboard?dates={season}&limit=500")
    # Send no User-Agent. Counterintuitively, ESPN answers 403 to a spoofed
    # browser UA ("Mozilla/5.0 ...") and 200 to the default Python one - the
    # header that looks like an evasion is the one that gets blocked.
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read()).get("events", [])


def parse_event(event: dict, tournament: str) -> Optional[dict]:
    competition = event["competitions"][0]
    status = competition.get("status", {}).get("type", {})
    if not status.get("completed"):
        return None
    # Extra time and penalties decide a tie, not the 90-minute result the
    # model is trained to predict. Only a clean full-time finish is used.
    if status.get("name") not in ("STATUS_FULL_TIME", "STATUS_FINAL"):
        return None

    sides = {c["homeAway"]: c for c in competition["competitors"]}
    if "home" not in sides or "away" not in sides:
        return None
    try:
        home_score = int(sides["home"]["score"])
        away_score = int(sides["away"]["score"])
    except (KeyError, TypeError, ValueError):
        return None

    venue = competition.get("venue") or {}
    address = venue.get("address") or {}
    return {
        "date": event["date"][:10],
        "home_team": team_name(sides["home"]["team"]["displayName"]),
        "away_team": team_name(sides["away"]["team"]["displayName"]),
        "home_score": home_score,
        "away_score": away_score,
        "tournament": tournament,
        "city": address.get("city", ""),
        "country": address.get("country", ""),
        "neutral": bool(competition.get("neutralSite")),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="uefa.nations", choices=sorted(LEAGUES))
    parser.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026])
    parser.add_argument("--write", action="store_true", help="without this, only report")
    args = parser.parse_args()

    tournament = LEAGUES[args.league]
    existing = pd.read_csv(CSV_PATH)
    have = {(r.date, r.home_team, r.away_team) for r in existing.itertuples()}

    fetched, skipped = [], []
    for season in args.seasons:
        events = fetch_season(args.league, season)
        parsed = [p for p in (parse_event(e, tournament) for e in events) if p]
        print(f"{args.league} {season}: {len(events)} events, {len(parsed)} completed")
        for row in parsed:
            key = (row["date"], row["home_team"], row["away_team"])
            (skipped if key in have else fetched).append(row)
            have.add(key)

    print(f"\nalready present: {len(skipped)}")
    print(f"new:             {len(fetched)}")
    for row in sorted(fetched, key=lambda r: r["date"]):
        print(f"  {row['date']}  {row['home_team']} {row['home_score']}:{row['away_score']} "
              f"{row['away_team']}{'  (neutral)' if row['neutral'] else ''}")

    unknown = {t for row in fetched for t in (row["home_team"], row["away_team"])} - (
        set(existing.home_team) | set(existing.away_team))
    if unknown:
        # A name the CSV has never seen means the model has no history for
        # that team - almost always a spelling mismatch rather than a debut.
        print(f"\nWARNING: names not in the existing data, check NAME_MAP: {sorted(unknown)}")

    if not fetched:
        print("\nNothing to add.")
        return
    if not args.write:
        print("\nDry run. Re-run with --write to append.")
        return

    combined = pd.concat([existing, pd.DataFrame(fetched)], ignore_index=True)
    combined = combined.sort_values(["date", "home_team", "away_team"], kind="stable")
    combined.to_csv(CSV_PATH, index=False)
    print(f"\nAppended {len(fetched)} rows -> {CSV_PATH} ({len(combined)} total)")


if __name__ == "__main__":
    main()

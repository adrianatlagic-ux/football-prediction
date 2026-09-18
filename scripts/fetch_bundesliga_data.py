"""Download Bundesliga (bl1) and 2. Bundesliga (bl2) match results from
OpenLigaDB - a free, public, no-key-required API for German football data
(https://www.openligadb.de/), not Apify. The Apify actor found for this
("Bundesliga Fixtures, Results and Standings Exporter") turned out to be a
paid wrapper around the exact same OpenLigaDB endpoints, so hitting the API
directly is strictly better: same real data, no per-row cost.

2. Bundesliga is fetched alongside 1. Bundesliga specifically so that clubs
promoted into the Bundesliga (e.g. Paderborn, Elversberg for 2026/27) have
real prior-season history for form/Elo features, instead of joining the
dataset with zero track record.

    python3 scripts/fetch_bundesliga_data.py

Writes one CSV per league per season to data/club_raw/, in the same shape as
the existing club_raw files (date, home_team, away_team, home_score,
away_score) so they concatenate straight into training.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import requests

OUT_DIR = Path(__file__).parent.parent / "data" / "club_raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://api.openligadb.de/getmatchdata"

# 1. Bundesliga and 2. Bundesliga, both from 2011 onward (matching the
# earliest Champions League season already in the dataset). OpenLigaDB
# labels a season by its starting year, e.g. 2026 = 2026/27.
LEAGUES = {
    "bl1": ("bundesliga", range(2011, 2027)),
    "bl2": ("bundesliga2", range(2011, 2026)),
}


def _final_score(match_results: list[dict]) -> tuple[int, int] | None:
    """OpenLigaDB lists halftime and fulltime as separate result rows for
    league matches (no extra time/penalties in the regular season) - take
    the fulltime one specifically rather than assuming list order/length."""
    for r in match_results:
        if r.get("resultTypeKind") == "After90Minutes":
            return r["pointsTeam1"], r["pointsTeam2"]
    return None


def fetch_season(shortcut: str, year: int) -> list[dict]:
    resp = requests.get(f"{BASE_URL}/{shortcut}/{year}", timeout=30)
    resp.raise_for_status()
    matches = resp.json()

    rows = []
    for m in matches:
        if not m.get("matchIsFinished"):
            continue
        score = _final_score(m.get("matchResults", []))
        if score is None:
            continue
        rows.append({
            "date": m["matchDateTime"][:10],
            "home_team": m["team1"]["teamName"],
            "away_team": m["team2"]["teamName"],
            "home_score": score[0],
            "away_score": score[1],
        })
    return rows


def main():
    total = 0
    for shortcut, (out_prefix, years) in LEAGUES.items():
        for year in years:
            rows = fetch_season(shortcut, year)
            if not rows:
                print(f"{shortcut} {year}/{year+1-2000}: no finished matches, skipping")
                continue
            rows.sort(key=lambda r: r["date"])
            season_label = f"{year}-{str(year + 1)[-2:]}"
            out_path = OUT_DIR / f"{out_prefix}_{season_label}.csv"
            with open(out_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["date", "home_team", "away_team", "home_score", "away_score"])
                writer.writeheader()
                writer.writerows(rows)
            print(f"{shortcut} {season_label}: {len(rows)} matches -> {out_path.relative_to(out_path.parent.parent.parent)}")
            total += len(rows)
            time.sleep(0.2)  # be polite to the free public API

    print(f"\nTotal: {total} matches")


if __name__ == "__main__":
    main()

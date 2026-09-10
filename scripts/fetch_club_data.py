"""Download the club-football training data pulled via Apify into local CSVs.

Reuses the dataset IDs from the Apify runs already executed this session
(Champions League via trovevault/champions-league-results-tables, Premier
League via jungle_synthesizer/premier-league-pulselive-fixtures-results-scraper)
so nothing gets re-scraped (re-running the actors would cost money again).

    python3 scripts/fetch_club_data.py

Writes one CSV per season to data/club_raw/, all in the same shape as
data/international_results.csv (date, home_team, away_team, home_score,
away_score) so they can be concatenated straight into training.
"""
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
APIFY_TOKEN = os.environ["APIFY_TOKEN"]
OUT_DIR = Path(__file__).parent.parent / "data" / "club_raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Champions League seasons (trovevault/champions-league-results-tables).
# Only the seasons that came back with a full ~125-match dataset - the
# thin ones (5-75 matches) aren't worth another round trip since the
# domestic-league data below is now the real backbone.
CL_DATASETS = {
    "2011-12": "9pkkMFDmHNpjuKWdp",
    "2014-15": "M1W9q1qHMZ5DPWtPS",
    "2015-16": "HBv7cV9O7IzQUanoK",
    "2016-17": "xzhd8pWV8R5CS9gXT",
    "2021-22": "4KuZRL7ckrEANbwf4",
    "2022-23": "Gh1HssHar5QL2Dh1D",
    "2023-24": "WEELwd3h2MqQUJIni",
    "2025-26": "SQA2EhZPcyrBGxgmG",
}

# Premier League seasons (jungle_synthesizer PulseLive scraper).
PL_DATASETS = {
    "2020-21": "SN2FSVNWtBpCX8DCP",
    "2021-22": "gPSie4VtomT2FxfRF",
    "2022-23": "L4oe7Bpl8j9gFKWmN",
    "2023-24": "tzVajZIIJlMeGHGjy",
    "2024-25": "Vh1t7bOeIpMu5xng8",
}

_COUNTRY_SUFFIX = re.compile(r"\s*\([A-Z]{3}\)$")


def _clean_team(name: str) -> str:
    return _COUNTRY_SUFFIX.sub("", name).strip()


def _fetch_all_items(dataset_id: str) -> list[dict]:
    items, offset, limit = [], 0, 1000
    while True:
        resp = requests.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items",
            params={"token": APIFY_TOKEN, "format": "json", "clean": "true",
                    "offset": offset, "limit": limit},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        items.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return items


def fetch_cl():
    for season, dataset_id in CL_DATASETS.items():
        items = _fetch_all_items(dataset_id)
        rows = [
            (it["localDate"], _clean_team(it["homeTeam"]), _clean_team(it["awayTeam"]),
             it["homeScore"], it["awayScore"])
            for it in items if it.get("homeScore") is not None
        ]
        out_path = OUT_DIR / f"cl_{season}.csv"
        with out_path.open("w", encoding="utf-8") as f:
            f.write("date,home_team,away_team,home_score,away_score\n")
            for date, home, away, hs, as_ in rows:
                f.write(f"{date},{home},{away},{hs},{as_}\n")
        print(f"  CL {season}: {len(rows)} matches -> {out_path.name}")


def fetch_pl():
    for season, dataset_id in PL_DATASETS.items():
        items = _fetch_all_items(dataset_id)
        rows = [
            (it["kickoff_utc"][:10], it["home_team"], it["away_team"], it["home_score"], it["away_score"])
            for it in items if it.get("home_score") is not None
        ]
        out_path = OUT_DIR / f"pl_{season}.csv"
        with out_path.open("w", encoding="utf-8") as f:
            f.write("date,home_team,away_team,home_score,away_score\n")
            for date, home, away, hs, as_ in rows:
                f.write(f"{date},{home},{away},{hs},{as_}\n")
        print(f"  PL {season}: {len(rows)} matches -> {out_path.name}")


if __name__ == "__main__":
    print("Champions League:")
    fetch_cl()
    print("Premier League:")
    fetch_pl()
    print("\nDone.")

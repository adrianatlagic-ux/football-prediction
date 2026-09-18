"""Refresh data/club_market_values_history.csv: DATED squad market values
for Bundesliga + 2. Bundesliga clubs, one snapshot per season instead of the
single current-season snapshot in src/club_market_values.py.

Why this exists: src/club_market_values.py applies ONE static value (scraped
for the current season) to every historical match regardless of date - a
clear look-ahead leak (a 2015 match gets the club's 2026 squad value). This
script fetches a value per (team, season) pair instead, so training features
can look up "what was this club worth at the time of this match" and stay
leakage-free.

Reuses the same actor as scripts/fetch_club_market_values.py
(incognito_mode/transfermarkt-competition-scraper), which already supports a
`season` input - just called once per season here instead of once total.
Same normalize/match pattern as that script (and scripts/fetch_club_crests.py)
for bridging Transfermarkt's naming against our canonical team names.

    python3 scripts/fetch_bundesliga_market_values_history.py

Costs roughly $0.003/club-row; ~18-36 rows per season x 16 seasons is a low
single-digit-dollar run on Apify's pay-per-event pricing.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()
APIFY_TOKEN = os.environ["APIFY_TOKEN"]
ACTOR_ID = "incognito_mode~transfermarkt-competition-scraper"
OUT_PATH = Path(__file__).parent.parent / "data" / "club_market_values_history.csv"
DATA_PATH = Path(__file__).parent.parent / "data" / "club_football_results.csv"

COMPETITION_CODES = ["L1", "L2"]
SEASONS = list(range(2011, 2027))  # 2011 means 2011/12; L2 has no 2026 season yet

# Same normalize/match approach as scripts/fetch_club_market_values.py -
# Transfermarkt's own naming ("1.FC Köln", "1.FC Nuremberg", "SG Dynamo
# Dresden") differs from our canonical names (from OpenLigaDB/Odds API:
# "1. FC Köln", "1. FC Nürnberg", "Dynamo Dresden") in spacing, translation,
# and extra prefixes - a fuzzy match is needed, not an exact dict.
_STRIP_TOKENS = ["FC", "SG", "SSV", "TSV", "VfL", "VfB", "1", "CF", "AFC", "KV", "SK", "AC", "BC", "SFP", "SCO", "AJ", "CD", "FK", "JK", "de", "du", "of"]
_ACCENTS = str.maketrans("éüöğçş", "euogcs")
_MIN_MATCH_LEN = 5

MANUAL_ALIASES = {
    "Bayer Leverkusen": "Bayer 04 Leverkusen",
    "1. FC Nürnberg": "1.FC Nuremberg",
    "1. FC Heidenheim": "1.FC Heidenheim 1846",
    "Dynamo Dresden": "SG Dynamo Dresden",
    "Hansa Rostock": "FC Hansa Rostock",
    "Jahn Regensburg": "SSV Jahn Regensburg",
    "Hertha Berlin": "Hertha BSC",
    "SC Paderborn": "SC Paderborn 07",
    "Elversberg": "SV 07 Elversberg",
    "Werder Bremen": "SV Werder Bremen",
    "Greuther Fürth": "SpVgg Greuther Fürth",
    "TSG Hoffenheim": "TSG 1899 Hoffenheim",
}


def _normalize(name: str) -> str:
    n = re.sub(r"\b(19|18|20)\d{2}\b", "", name)
    for tok in _STRIP_TOKENS:
        n = re.sub(rf"\b{re.escape(tok)}\b", "", n)
    n = n.translate(_ACCENTS)
    n = re.sub(r"[^a-zA-Z0-9 ]", "", n)
    return re.sub(r"\s+", " ", n).strip().lower()


def _run_actor_and_get_items(input_payload: dict) -> list[dict]:
    run_resp = requests.post(
        f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs",
        params={"token": APIFY_TOKEN},
        json=input_payload,
        timeout=30,
    )
    run_resp.raise_for_status()
    run_id = run_resp.json()["data"]["id"]

    while True:
        status_resp = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            params={"token": APIFY_TOKEN}, timeout=15,
        )
        status = status_resp.json()["data"]["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        time.sleep(2)

    if status != "SUCCEEDED":
        raise RuntimeError(f"Apify run {run_id} ended with status {status}")

    dataset_id = status_resp.json()["data"]["defaultDatasetId"]
    items_resp = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        params={"token": APIFY_TOKEN, "format": "json", "clean": "true"},
        timeout=30,
    )
    items_resp.raise_for_status()
    return items_resp.json()


def _match(team: str, mv_items: list[tuple[str, str, int]]) -> int | None:
    if team in MANUAL_ALIASES:
        alias = MANUAL_ALIASES[team]
        for _, orig, val in mv_items:
            if orig == alias:
                return val
    nt = _normalize(team)
    for norm_mv, _, val in mv_items:
        if nt == norm_mv:
            return val
    candidates = []
    for norm_mv, _, val in mv_items:
        shorter = min(len(nt), len(norm_mv))
        if shorter >= _MIN_MATCH_LEN and (nt in norm_mv or norm_mv in nt):
            candidates.append(val)
    return candidates[0] if candidates else None


def main():
    our_teams = sorted({
        t for col in ("home_team", "away_team") for t in pd.read_csv(DATA_PATH)[col]
    })

    rows = []
    missing_by_season = {}
    for season in SEASONS:
        codes = ["L1"] if season == 2026 else COMPETITION_CODES
        print(f"Season {season}/{str(season + 1)[-2:]} ({'+'.join(codes)})...")
        items = _run_actor_and_get_items({
            "competitionCodes": codes,
            "season": season,
            "includeStandings": False,
            "maxItems": 40,
        })
        mv_items = [(_normalize(it["clubName"]), it["clubName"], it["totalMarketValue"])
                    for it in items if it.get("totalMarketValue")]

        season_missing = []
        for t in our_teams:
            val = _match(t, mv_items)
            if val is not None:
                rows.append({"season_start_year": season, "team": t, "market_value": val})
            else:
                season_missing.append(t)
        if season_missing:
            missing_by_season[season] = season_missing

    rows.sort(key=lambda r: (r["season_start_year"], r["team"]))
    df = pd.DataFrame(rows)
    df.to_csv(OUT_PATH, index=False)
    print(f"\n{len(rows)} (season, team) rows -> {OUT_PATH}")
    print(f"{df['team'].nunique()} distinct teams matched across {df['season_start_year'].nunique()} seasons")

    # Not every team in our overall dataset (CL/PL/etc.) plays in Germany -
    # this is expected to be large and is not an error.
    all_missing_teams = set()
    for s, teams in missing_by_season.items():
        all_missing_teams.update(teams)
    german_looking = [t for t in sorted(all_missing_teams) if t in our_teams]
    print(f"{len(all_missing_teams)} teams had no match in at least one season (expected for non-German clubs)")


if __name__ == "__main__":
    main()

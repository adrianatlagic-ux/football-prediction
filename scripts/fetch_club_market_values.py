"""Refresh src/club_market_values.py from Transfermarkt via Apify.

Uses incognito_mode/transfermarkt-competition-scraper (one row per club:
league table position merged with total squad market value) across Champions
League + the biggest European domestic leagues, then matches Transfermarkt's
own club-naming convention against our canonical team names (the ones
data/club_football_results.csv and The Odds API use).

    python3 scripts/fetch_club_market_values.py

Requires APIFY_TOKEN in .env. Costs roughly $0.05-0.10 per run (~300 club
rows at $0.003 each) - Apify's pay-per-event pricing, not a subscription.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()
APIFY_TOKEN = os.environ["APIFY_TOKEN"]
ACTOR_ID = "incognito_mode~transfermarkt-competition-scraper"
OUT_PATH = Path(__file__).parent.parent / "src" / "club_market_values.py"
DATA_PATH = Path(__file__).parent.parent / "data" / "club_football_results.csv"

# Transfermarkt competition codes covering Champions League + the biggest
# European domestic leagues. Smaller leagues (Kazakhstan, Belarus, Russia,
# Ukraine, Israel, Serbia, Moldova, Cyprus, Romania, Slovenia...) are
# deliberately left out - clubs from those leagues fall back to a market
# value of 0, same as src/market_values.py does for uncovered national teams.
COMPETITION_CODES = [
    "CL", "GB1", "GB2", "ES1", "L1", "IT1", "FR1", "PO1", "NL1", "TR1",
    "BE1", "C1", "SC1", "KR1", "TS1", "PL1", "SE1",
]

# Tokens stripped when normalizing a club name for matching, on both sides
# (Transfermarkt's naming vs. our canonical names) - founding years, legal-
# entity suffixes, and generic prefixes that differ between sources but don't
# distinguish one club from another.
_STRIP_TOKENS = ["FC", "CF", "AFC", "KV", "SK", "AC", "BC", "SFP", "SCO", "AJ", "CD", "FK", "JK", "de", "du", "of"]
_ACCENTS = str.maketrans("éüöğçş", "euogcs")
_MIN_MATCH_LEN = 6  # shorter than this, a substring match is too likely to be a false positive (see "Paris FC" vs "Paris Saint Germain")

# Manual overrides for club-name pairs the automatic matcher can't bridge
# (usually because the shared "core" name is under _MIN_MATCH_LEN chars).
MANUAL_ALIASES = {
    "Bayer Leverkusen": "Bayer 04 Leverkusen",
    "Schalke 04": "FC Schalke 04",
    "Slavia Praha": "SK Slavia Praha",
    "Sporting Lisbon": "Sporting CP",
}


def _normalize(name: str) -> str:
    n = re.sub(r"\b(19|18)\d{2}\b", "", name)
    for tok in _STRIP_TOKENS:
        n = re.sub(rf"\b{re.escape(tok)}\b", "", n)
    n = re.sub(r"^(1\.|AS |AZ )", "", n)
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
    run = run_resp.json()["data"]
    run_id = run["id"]

    while True:
        status_resp = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            params={"token": APIFY_TOKEN}, timeout=15,
        )
        status = status_resp.json()["data"]["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        time.sleep(3)

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


def main():
    print(f"Hole Marktwerte für {len(COMPETITION_CODES)} Wettbewerbe von Transfermarkt...")
    items = _run_actor_and_get_items({
        "competitionCodes": COMPETITION_CODES,
        "season": 2025,
        "includeStandings": True,
        "maxItems": 500,
    })
    mv_items = [(_normalize(it["clubName"]), it["clubName"], it["totalMarketValue"])
                for it in items if it.get("totalMarketValue")]
    print(f"  {len(mv_items)} Klub-Datensätze geholt.")

    our_teams = sorted({
        t for col in ("home_team", "away_team")
        for t in __import__("pandas").read_csv(DATA_PATH)[col]
    })

    mv_by_orig = {orig: val for _, orig, val in mv_items}
    result: dict[str, int] = {}
    missing = []
    for t in our_teams:
        if t in MANUAL_ALIASES and MANUAL_ALIASES[t] in mv_by_orig:
            result[t] = mv_by_orig[MANUAL_ALIASES[t]]
            continue
        nt = _normalize(t)
        candidates = []
        for norm_mv, orig_mv, val in mv_items:
            if nt == norm_mv:
                candidates = [val]
                break
            shorter = min(len(nt), len(norm_mv))
            if shorter >= _MIN_MATCH_LEN and (nt in norm_mv or norm_mv in nt):
                candidates.append(val)
        if candidates:
            result[t] = candidates[0]
        else:
            missing.append(t)

    print(f"  {len(result)}/{len(our_teams)} Teams gematcht, {len(missing)} ohne Marktwert (Kaltstart-Fallback).")

    lines = [
        '"""',
        "Total squad market values (EUR) for club football teams, from Transfermarkt.",
        "Covers Champions League + the biggest European domestic leagues. Regenerate",
        "with: python3 scripts/fetch_club_market_values.py",
        "",
        "Coverage is intentionally partial: smaller leagues are not included, so clubs",
        "from those leagues fall back to 0 (see get_market_value below), the same way",
        "src/market_values.py does for uncovered national teams.",
        '"""',
        "",
        "MARKET_VALUES: dict[str, int] = {",
    ]
    for name, val in sorted(result.items(), key=lambda kv: -kv[1]):
        esc = name.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    "{esc}": {val},')
    lines += [
        "}",
        "",
        "_MAX_VALUE = max(MARKET_VALUES.values())",
        "",
        "",
        "def get_market_value(team: str) -> float:",
        "    return float(MARKET_VALUES.get(team, 0))",
        "",
        "",
        "def get_market_value_ratio(home: str, away: str) -> float:",
        "    h = get_market_value(home)",
        "    a = get_market_value(away)",
        "    if h == 0 and a == 0:",
        "        return 1.0",
        "    if a == 0:",
        "        return 2.0",
        "    if h == 0:",
        "        return 0.5",
        "    return h / a",
        "",
        "",
        "def get_market_value_normalized(team: str) -> float:",
        "    return get_market_value(team) / _MAX_VALUE",
        "",
    ]
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Geschrieben: {OUT_PATH}")


if __name__ == "__main__":
    main()

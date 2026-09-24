"""Collect Transfermarkt ids for every team we predict, one row per team.

The id is what unlocks a squad page, and therefore per-player values and
injury records. Today it exists nowhere usable: the national ids sit inside
data/national_market_values.csv as a side effect of a market-value fetch, and
the club path (scripts/fetch_club_market_values.py) works from competition
codes and discards ids entirely.

    python3 scripts/build_team_registry.py --competition bundesliga
    python3 scripts/build_team_registry.py --all

Club competitions are read through Apify, which understands the Transfermarkt
competition page. National teams are not: the actor rejects the participant
page URL, so their rows come from the CSV that scripts/fetch_national_market_values.py
already produces. That asymmetry is tolerable because a registry is rebuilt
once a season, not once a matchday.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.competitions import COMPETITIONS, get
from src.squad_data import ACTOR, ENDPOINT

OUT = ROOT / "data" / "team_registry.csv"
NATIONAL = ROOT / "data" / "national_market_values.csv"
FIELDS = ["competition", "team", "transfermarkt_id", "squad_size",
          "squad_value_eur", "determined_date"]


def from_apify(url: str, token: str) -> list:
    request = urllib.request.Request(
        ENDPOINT.format(ACTOR, token), method="POST",
        data=json.dumps({
            "startUrls": [url], "recordType": "competition", "language": "com",
            "includeCompetitionClubs": True, "includeClubSquad": False,
            "includeMarketValueHistory": False, "includeTransferHistory": False,
            # 0 is documented as unlimited but returns only the competition row.
            "maxResults": 200,
        }).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        items = json.loads(response.read().decode())
    return [i for i in items if i.get("recordType") == "club" and i.get("id")]


def rows_for(key: str, token: str) -> list:
    competition = get(key)
    today = date.today().isoformat()
    if competition.registry_url is None:
        if not NATIONAL.exists():
            raise SystemExit(
                f"{key} takes its ids from {NATIONAL.name}; run "
                "scripts/fetch_national_market_values.py first")
        with NATIONAL.open(encoding="utf-8") as fh:
            return [{"competition": key, "team": r["team"],
                     "transfermarkt_id": r["transfermarkt_id"],
                     "squad_size": r.get("squad_size") or "",
                     "squad_value_eur": r["market_value_total_eur"],
                     "determined_date": r.get("determined_date") or today}
                    for r in csv.DictReader(fh)]
    return [{"competition": key, "team": c["name"], "transfermarkt_id": c["id"],
             "squad_size": c.get("squadSize") or "",
             "squad_value_eur": c.get("squadMarketValueTotalEur") or "",
             "determined_date": today}
            for c in from_apify(competition.registry_url, token)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--competition", action="append", default=[],
                    help="repeatable; omit with --all")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    keys = sorted(COMPETITIONS) if args.all else args.competition
    if not keys:
        raise SystemExit("choose --competition <key> or --all")
    token = os.environ.get("APIFY_TOKEN", "")

    # Keep competitions we are not refreshing; replace the ones we are.
    kept = []
    if args.out.exists():
        with args.out.open(encoding="utf-8") as fh:
            kept = [r for r in csv.DictReader(fh) if r["competition"] not in keys]

    fresh = []
    for key in keys:
        rows = rows_for(key, token)
        # An empty answer is transient often enough that writing it out would
        # quietly drop a whole competition from the registry. Refuse instead.
        if not rows:
            raise SystemExit(
                f"{key}: no teams returned - registry left untouched, try again")
        print(f"  {key:18} {len(rows):3} Mannschaften")
        fresh.extend(rows)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(kept + fresh, key=lambda r: (r["competition"], r["team"])))
    print(f"\n{len(kept) + len(fresh)} Zeilen -> {args.out.relative_to(ROOT)}"
          f"  ({len(kept)} unveraendert uebernommen)")


if __name__ == "__main__":
    main()

"""Write the final scores into tip log lines that have none.

    python3 scripts/backfill_results.py            # report only
    python3 scripts/backfill_results.py --write

From now on the server saves each score itself (src/scheduler.py). This is for
the matches logged before that, whose results the live feed has already
forgotten (it only reaches back about a month): the live feed first, then
ESPN's scoreboard of the Nations League by season (the same source the feed
uses; only 90-minute scores count).
"""
import argparse
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from src import log_store  # noqa: E402
import fetch_national_results as espn  # noqa: E402

DEFAULT_API = "https://football-prediction.fly.dev"


def espn_nations_results(seasons=(2025, 2026)) -> list[dict]:
    out = []
    for season in seasons:
        for event in espn.fetch_season("uefa.nations", season):
            p = espn.parse_event(event, "UEFA Nations League")
            if p:
                out.append({"home_team": p["home_team"], "away_team": p["away_team"],
                            "commence_time": p["date"], "completed": True,
                            "home_score": p["home_score"], "away_score": p["away_score"]})
    return out


def espn_club_results(entries) -> list[dict]:
    """ESPN's scoreboard for the days of the matches still without a score,
    Bundesliga and Champions League (single days work, ranges do not)."""
    import api.app as app
    days = sorted({e["commence_time"][:10] for e in entries if log_store.slug(e) in ("bundesliga", "champions-league")})
    out = []
    for league in ("ger.1", "uefa.champions"):
        for day in days:
            url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
                   f"?limit=100&dates={day.replace('-', '')}")
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    events = json.loads(r.read()).get("events", [])
            except Exception:
                continue
            for event in events:
                comp = event["competitions"][0]
                st = comp["status"]["type"]
                if st.get("name") not in ("STATUS_FULL_TIME", "STATUS_FINAL") or comp["status"].get("period") != 2:
                    continue
                side = {c["homeAway"]: c for c in comp["competitors"]}
                out.append({"home_team": app._espn_team(side["home"]["team"]["displayName"]),
                            "away_team": app._espn_team(side["away"]["team"]["displayName"]),
                            "commence_time": event["date"][:10], "completed": True,
                            "home_score": int(side["home"]["score"]), "away_score": int(side["away"]["score"])})
    return out


def alias_matches(entries, results) -> list[dict]:
    """Results for entries whose team names ESPN spells differently ("Schalke 04"
    for "FC Schalke 04", "LASK Linz" for "LASK"): same day, and each side's
    name contained in the other. The result carries the log's own names."""
    def same(a, b):
        a, b = log_store.norm(a), log_store.norm(b)
        return len(min(a, b, key=len)) >= 4 and (a in b or b in a)
    out = []
    for e in entries:
        day = e["commence_time"][:10]
        for r in results:
            if r["commence_time"][:10] == day and same(e["home_team"], r["home_team"]) \
                    and same(e["away_team"], r["away_team"]):
                out.append({**r, "home_team": e["home_team"], "away_team": e["away_team"],
                            "commence_time": e["commence_time"]})
                break
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    entries = log_store.load_tips()
    now = datetime.now(timezone.utc)
    todo = log_store.unsettled(entries, now)
    print(f"{len(entries)} Spiele geloggt, {len(todo)} ohne Ergebnis und laenger als 2 h vorbei.")

    live = json.load(urllib.request.urlopen(f"{args.api}/real-results", timeout=60))["results"]
    n_live = log_store.settle(entries, live, now, source="espn")
    n_nations = log_store.settle(entries, espn_nations_results(), now, source="espn")
    rest = log_store.unsettled(entries, now)
    club = espn_club_results(rest)
    n_clubs = log_store.settle(entries, club + alias_matches(rest, club), now, source="espn")
    left = log_store.unsettled(entries, now)
    print(f"Ergebnisse ergaenzt: {n_live} aus dem Live-Feed, {n_nations} aus ESPN (Nations League), "
          f"{n_clubs} aus ESPN (Bundesliga/Champions League).")
    print(f"Weiterhin ohne Ergebnis: {len(left)} {dict(Counter(log_store.slug(e) for e in left))}")
    for e in left:
        print(f"  {e['commence_time'][:10]}  {e['home_team']} - {e['away_team']}")
    if args.write:
        log_store.write_tips(entries)
        print("Geschrieben nach data/logs/tips/.")
    else:
        print("Nur Bericht. Mit --write speichern.")


if __name__ == "__main__":
    main()

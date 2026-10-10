"""Chance data per Bundesliga match: xG (Understat) and shots (football-data.co.uk).

    python3 scripts/fetch_club_stats.py            # every season, cached downloads reused
    python3 scripts/fetch_club_stats.py --refresh  # download the current season again

Step 1 of docs/form_xg_plan.md. Writes data/club_stats/bundesliga_<season>.csv,
one row per match of data/club_raw (date, teams in our spelling, final score,
xG, shots, shots on target) - a value is empty where the source has none.

The sources spell teams their own way ("Borussia M.Gladbach", "M'gladbach").
Instead of a hand-kept list, each source's names are mapped to ours by the
matches themselves: a source match and one of ours on the same day (one day
either side, for time zones) with the same score vote for the pairing of
their team names; the majority wins. A match then joins on day and mapped
names, and its score must agree. Anything left over is reported, not guessed.

Raw downloads are kept in data/club_stats/raw/ so a rerun does not ask the
sites again; finished seasons never change.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.club_data_loader import load_completed_matches  # noqa: E402

OUT = ROOT / "data" / "club_stats"
RAW = OUT / "raw"
UNDERSTAT_FIRST = 2014       # Understat's Bundesliga starts with 2014-15
FDCO_FIRST = 2011
HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest", "Accept-Encoding": "gzip"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
        body = r.read()
        return gzip.decompress(body) if r.headers.get("Content-Encoding") == "gzip" else body


def _cached(name: str, url: str, refresh: bool) -> bytes | None:
    path = RAW / name
    if path.exists() and not refresh:
        return path.read_bytes()
    try:
        body = _get(url)
    except Exception as exc:
        print(f"  {name}: not available ({type(exc).__name__}: {exc})")
        return None
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def understat(start: int, refresh: bool) -> list[dict]:
    body = _cached(f"understat_bundesliga_{start}.json",
                   f"https://understat.com/getLeagueData/Bundesliga/{start}", refresh)
    if not body:
        return []
    out = []
    for m in json.loads(body).get("dates", []):
        if not m.get("isResult"):
            continue
        out.append({"date": date.fromisoformat(m["datetime"][:10]), "home": m["h"]["title"], "away": m["a"]["title"],
                    "hg": int(m["goals"]["h"]), "ag": int(m["goals"]["a"]),
                    "home_xg": float(m["xG"]["h"]), "away_xg": float(m["xG"]["a"])})
    return out


def fdco(start: int, refresh: bool) -> list[dict]:
    code = f"{start % 100:02d}{(start + 1) % 100:02d}"
    body = _cached(f"fdco_D1_{code}.csv", f"https://www.football-data.co.uk/mmz4281/{code}/D1.csv", refresh)
    if not body:
        return []
    out = []
    for r in csv.DictReader(io.StringIO(body.decode("utf-8-sig", errors="replace"))):
        try:
            d, m, y = r["Date"].split("/")
            day = date(int(y) + (2000 if len(y) == 2 else 0), int(m), int(d))
            row = {"date": day, "home": r["HomeTeam"], "away": r["AwayTeam"],
                   "hg": int(r["FTHG"]), "ag": int(r["FTAG"])}
        except (KeyError, ValueError):
            continue
        for ours, theirs in (("home_shots", "HS"), ("away_shots", "AS"), ("home_sot", "HST"), ("away_sot", "AST")):
            try:
                row[ours] = int(r[theirs])
            except (KeyError, ValueError):
                row[ours] = None
        out.append(row)
    return out


def _near(day: date):
    return (day - timedelta(days=1), day, day + timedelta(days=1))


def name_map(source: list[dict], ours: list[dict]) -> dict:
    """Source team name -> our team name, by majority over unambiguous matches."""
    by_key = defaultdict(list)
    for m in ours:
        by_key[(m["date"], m["hg"], m["ag"])].append(m)
    votes = defaultdict(Counter)
    for s in source:
        cands = [m for d in _near(s["date"]) for m in by_key.get((d, s["hg"], s["ag"]), [])]
        if len(cands) == 1:
            votes[s["home"]][cands[0]["home"]] += 1
            votes[s["away"]][cands[0]["away"]] += 1
    return {name: c.most_common(1)[0][0] for name, c in votes.items() if c.most_common(1)[0][1] >= 2}


def join(source: list[dict], ours: list[dict], fields: list[str]) -> tuple[dict, list]:
    mapping = name_map(source, ours)
    index = {(m["date"], m["home"], m["away"]): m for m in ours}
    joined, problems = {}, []
    for s in source:
        h, a = mapping.get(s["home"]), mapping.get(s["away"])
        match = next((index[(d, h, a)] for d in _near(s["date"]) if (d, h, a) in index), None)
        if match is None:
            problems.append(f"no match for {s['date']} {s['home']} - {s['away']}")
            continue
        if (match["hg"], match["ag"]) != (s["hg"], s["ag"]):
            problems.append(f"score differs {s['date']} {s['home']} - {s['away']}: "
                            f"{s['hg']}:{s['ag']} vs ours {match['hg']}:{match['ag']}")
            continue
        joined[(match["date"], match["home"], match["away"])] = {k: s.get(k) for k in fields}
    return joined, problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="download the latest season again")
    args = parser.parse_args()
    H = load_completed_matches()
    H = H[H.competition == "bundesliga"]
    latest = int(H.season.max()[:4])
    OUT.mkdir(parents=True, exist_ok=True)
    total = Counter()
    for season, games in sorted(H.groupby("season")):
        start = int(season[:4])
        refresh = args.refresh and start == latest
        ours = [{"date": r.date.date() if hasattr(r.date, "date") else date.fromisoformat(str(r.date)[:10]),
                 "home": r.home_team, "away": r.away_team, "hg": int(r.home_goals), "ag": int(r.away_goals)}
                for r in games.itertuples()]
        xg, xg_problems = ({}, [])
        if start >= UNDERSTAT_FIRST:
            xg, xg_problems = join(understat(start, refresh), ours, ["home_xg", "away_xg"])
        shots, shot_problems = ({}, [])
        if start >= FDCO_FIRST:
            shots, shot_problems = join(fdco(start, refresh), ours, ["home_shots", "away_shots", "home_sot", "away_sot"])
        path = OUT / f"bundesliga_{season}.csv"
        cols = ["date", "home_team", "away_team", "home_goals", "away_goals",
                "home_xg", "away_xg", "home_shots", "away_shots", "home_sot", "away_sot"]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for m in sorted(ours, key=lambda m: (m["date"], m["home"])):
                key = (m["date"], m["home"], m["away"])
                x, s = xg.get(key, {}), shots.get(key, {})
                w.writerow([m["date"].isoformat(), m["home"], m["away"], m["hg"], m["ag"],
                            x.get("home_xg", ""), x.get("away_xg", ""), s.get("home_shots", ""),
                            s.get("away_shots", ""), s.get("home_sot", ""), s.get("away_sot", "")])
        total["matches"] += len(ours)
        total["xg"] += len(xg)
        total["shots"] += len(shots)
        print(f"{season}: {len(ours)} matches, xG {len(xg)}, shots {len(shots)}"
              + (f"  | {len(xg_problems) + len(shot_problems)} problems" if xg_problems or shot_problems else ""))
        for p in (xg_problems + shot_problems)[:5]:
            print("   ", p)
    print(f"\ntotal: {total['matches']} matches, xG for {total['xg']}, shots for {total['shots']}")


if __name__ == "__main__":
    main()

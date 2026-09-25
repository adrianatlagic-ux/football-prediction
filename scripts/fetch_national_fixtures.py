"""Write the next national-team matchday to a frontend fixtures file.

Mirrors frontend/src/bl_fixtures.json so the site can switch competitions
without a second code path.

    python3 scripts/fetch_national_fixtures.py                  # dry run
    python3 scripts/fetch_national_fixtures.py --write

A "matchday" here is one calendar day in Europe/Berlin: national windows run
several days in a row, and a slip covers one evening, not the whole break.
Team names go through the same map as the results importer, so a fixture and
its history refer to the same team.
"""
import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fetch_national_results import NAME_MAP, team_name

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "frontend" / "src" / "nl_fixtures.json"
TZ = ZoneInfo("Europe/Berlin")
ACCENTS = str.maketrans("äöüÄÖÜßàáâãéèêíóôõúçñ", "aouAOUsaaaaeeeioooucn")


def slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.translate(ACCENTS))
    plain = plain.encode("ascii", "ignore").decode().lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", plain)).strip("_")


def fetch(league: str, season: int) -> list[dict]:
    url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}"
           f"/scoreboard?dates={season}&limit=500")
    # No User-Agent on purpose - ESPN 403s a spoofed browser one.
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read()).get("events", [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="uefa.nations")
    parser.add_argument("--season", type=int, default=datetime.now(TZ).year)
    parser.add_argument("--days", type=int, default=1, help="how many matchdays to include, today first")
    parser.add_argument("--past-days", type=int, default=7,
                        help="also keep matchdays from this many days back, so their results stay on the site")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    now = datetime.now(TZ)
    today = now.date()
    upcoming, past = [], []
    for event in fetch(args.league, args.season):
        kickoff = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(TZ)
        # Today's games stay in even after kickoff: the site shows them with
        # their live or final score instead of dropping them mid-evening.
        if kickoff.date() < today:
            if (today - kickoff.date()).days > args.past_days:
                continue
            target = past
        else:
            target = upcoming
        sides = {c["homeAway"]: c["team"]["displayName"] for c in event["competitions"][0]["competitors"]}
        if "home" not in sides or "away" not in sides:
            continue
        target.append((kickoff, team_name(sides["home"]), team_name(sides["away"])))

    if not upcoming:
        print("No upcoming fixtures found.")
        return

    days = set(sorted({k.date() for k, _, _ in upcoming})[: args.days]) | {k.date() for k, _, _ in past}
    fixtures = []
    for kickoff, home, away in sorted(past + upcoming):
        if kickoff.date() not in days:
            continue
        fixtures.append({
            "group": kickoff.strftime("%a %d %b"),
            "date": kickoff.date().isoformat(),
            "time": kickoff.strftime("%H:%M"),
            "home_team": home,
            "away_team": away,
            "match_id": f"{slug(home)}_vs_{slug(away)}_nl",
        })

    duplicates = [i for i, n in Counter(f["match_id"] for f in fixtures).items() if n > 1]
    if duplicates:
        raise SystemExit(f"Duplicate match_id, fix the slug rule: {duplicates}")

    for f in fixtures:
        print(f"  {f['date']} {f['time']}  {f['home_team']} vs {f['away_team']}  ({f['match_id']})")
    print(f"\n{len(fixtures)} fixtures across {len(days)} matchday(s)")

    if not args.write:
        print("Dry run. Re-run with --write.")
        return
    OUT_PATH.write_text(json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()

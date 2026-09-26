"""The season's fixture lists, built on the server from ESPN.

The site used to carry its fixtures inside the frontend bundle, so a new
matchday only appeared after someone regenerated a file and redeployed. The
daily job now rebuilds data/fixtures/{bl,cl,nl}.json and GET /fixtures serves
them; the page falls back to the bundled files only if that fails.

The whole season is listed, but a prediction is only shown from 48 hours
before kickoff (the daily job's window): a forecast for May made in
September would know nothing of the spring, and would look it.

Team names go through the same maps as the results (src/results_update.py),
so a fixture, its prediction and its result all name a team the same way.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fixtures"
TZ = ZoneInfo("Europe/Berlin")
LEAGUES = {"bl": "ger.1", "cl": "uefa.champions", "nl": "uefa.nations"}
CL_STAGES = {"league-phase": "League Phase", "knockout-round-playoffs": "Knockout Playoffs",
             "round-of-16": "Round of 16", "quarterfinals": "Quarter-finals",
             "semifinals": "Semi-finals", "final": "Final"}


def season_bounds(today: date) -> tuple:
    start = today.year if today.month >= 7 else today.year - 1
    return date(start, 7, 1), date(start + 1, 6, 30)


def _events(league: str, years) -> list:
    import urllib.request
    seen, out = set(), []
    for year in years:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={year}&limit=1000"
        with urllib.request.urlopen(url, timeout=20) as response:
            for event in json.loads(response.read()).get("events", []):
                if event.get("id") not in seen:
                    seen.add(event.get("id"))
                    out.append(event)
    return out


def build(key: str, today: date | None = None, events=None) -> list:
    from scripts.build_club_training_data import _canon
    from scripts.fetch_national_fixtures import slug
    from scripts.fetch_national_results import team_name
    today = today or date.today()
    first, last = season_bounds(today)
    events = events if events is not None else _events(LEAGUES[key], {first.year, last.year})
    name = team_name if key == "nl" else _canon
    rows = []
    for event in events:
        kickoff = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(TZ)
        if not first <= kickoff.date() <= last:
            continue
        sides = {c["homeAway"]: c["team"]["displayName"] for c in event["competitions"][0]["competitors"]}
        if "home" not in sides or "away" not in sides:
            continue
        home, away = name(sides["home"]), name(sides["away"])
        rows.append({"kickoff": kickoff, "home_team": home, "away_team": away,
                     "stage": (event.get("season") or {}).get("slug", ""),
                     "match_id": f"{slug(home)}_vs_{slug(away)}_{key}"})
    rows.sort(key=lambda r: (r["kickoff"], r["home_team"]))

    # ESPN gives no matchday number. A team plays once per matchday (the
    # Bundesliga, the Champions League's league phase), so a match belongs to
    # the one after both teams' previous games.
    played = defaultdict(int)
    out, seen = [], set()
    for r in rows:
        if r["match_id"] in seen:
            continue
        seen.add(r["match_id"])
        league_phase = key == "cl" and r["stage"] in ("league-phase", "")
        if key == "bl" or league_phase:
            matchday = max(played[r["home_team"]], played[r["away_team"]]) + 1
            played[r["home_team"]] = played[r["away_team"]] = matchday
            group = f"Spieltag {matchday}" if key == "bl" else f"Matchday {matchday}"
        elif key == "cl":
            group = CL_STAGES.get(r["stage"], r["stage"] or "Knockout")
        else:
            group = r["kickoff"].strftime("%a %d %b")
        out.append({"group": group, "date": r["kickoff"].date().isoformat(),
                    "time": r["kickoff"].strftime("%H:%M"), "home_team": r["home_team"],
                    "away_team": r["away_team"], "match_id": r["match_id"]})
    return out


def write_all(today: date | None = None) -> dict:
    """Rebuild every file; a competition that fails keeps its last list."""
    OUT.mkdir(parents=True, exist_ok=True)
    counts = {}
    for key in LEAGUES:
        try:
            fixtures = build(key, today)
        except Exception as exc:
            counts[key] = f"error: {type(exc).__name__}: {exc}"
            continue
        if fixtures:
            (OUT / f"{key}.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
        counts[key] = len(fixtures)
    return counts


def load_all() -> dict:
    """The served lists, each falling back to the bundled frontend file."""
    out = {}
    for key in LEAGUES:
        for path in (OUT / f"{key}.json", ROOT / "frontend" / "src" / f"{key}_fixtures.json"):
            try:
                out[key] = json.loads(path.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                continue
    return out

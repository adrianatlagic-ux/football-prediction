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


# A matchday is a run of kickoffs with no gap longer than this: Friday to
# Sunday, or Tuesday to Thursday. Sunday evening to a Tuesday midweek round
# is longer, so an English week splits into two matchdays.
MATCHDAY_GAP_HOURS = 36
# Fewer games than this in a block are rescheduled matches, not a matchday.
MIN_MATCHDAY_GAMES = 6


def _matchdays(rows: list, key: str) -> dict:
    """Matchday number per row index, for the Bundesliga and the league phase.

    ESPN gives no matchday number. Blocks of kickoffs close together are
    numbered in order. A game played on its own later - a postponed match -
    belongs to the earliest matchday both teams are still missing, which
    keeps it from pushing every later matchday out of step, as counting each
    team's games did.
    """
    idx = [i for i, r in enumerate(rows)
           if key == "bl" or (key == "cl" and r["stage"] in ("league-phase", ""))]
    blocks, current = [], []
    for i in idx:
        if current and (rows[i]["kickoff"] - rows[current[-1]]["kickoff"]).total_seconds() > MATCHDAY_GAP_HOURS * 3600:
            blocks.append(current)
            current = []
        current.append(i)
    if current:
        blocks.append(current)
    result, played, number = {}, defaultdict(set), 0
    for block in blocks:
        if len(block) >= MIN_MATCHDAY_GAMES:
            number += 1
        for i in block:
            home, away = rows[i]["home_team"], rows[i]["away_team"]
            if len(block) >= MIN_MATCHDAY_GAMES and number not in played[home] | played[away]:
                md = number
            else:
                md = next(n for n in range(1, number + 60) if n not in played[home] | played[away])
            played[home].add(md)
            played[away].add(md)
            result[i] = md
    return result


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

    matchdays = _matchdays(rows, key)
    out, ids = [], {}
    for i, r in enumerate(rows):
        # The same pairing with the same home side can meet twice in a season
        # (league phase, then a knockout round). The first keeps the plain id,
        # which cached predictions already use; a later one gets its date.
        match_id = r["match_id"]
        if match_id in ids and ids[match_id] != r["kickoff"].date():
            match_id = f"{match_id}_{r['kickoff'].strftime('%Y%m%d')}"
        elif match_id in ids:
            continue                      # the same match listed twice
        ids.setdefault(r["match_id"], r["kickoff"].date())
        if i in matchdays:
            group = f"Spieltag {matchdays[i]}" if key == "bl" else f"Matchday {matchdays[i]}"
        elif key == "cl":
            group = CL_STAGES.get(r["stage"], r["stage"] or "Knockout")
        else:
            group = r["kickoff"].strftime("%a %d %b")
        out.append({"group": group, "date": r["kickoff"].date().isoformat(),
                    "time": r["kickoff"].strftime("%H:%M"), "home_team": r["home_team"],
                    "away_team": r["away_team"], "match_id": match_id})
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

"""Log the combo tickets the page shows - and the old rule's - before kickoff.

    python3 scripts/log_combos.py --api https://football-prediction.fly.dev

Two rules are logged on the same matches and compared once enough tickets
have settled (scripts/grade_combos.py):

    ai_pick    the rule the page shows: the published AI picks
    agree      only legs the model agrees with, the AI's picks first

The older rules (market, legacy_v3, ki) are no longer logged since
14 November; their rows stay in the log.

Every version the page shows is logged: whenever a rule's ticket of a size
changes its legs, the new version is appended with its time. A ticket
exists until its first leg kicks off - a started match leaves the combos -
so the last version logged is the one still placeable at kickoff, and each
earlier one is what the page showed in between. Odds moving on the same legs
do not make a new version.

The server (src/scheduler.py) no longer appends every version. It logs each
ticket ONCE, about an hour before its first match, when the AI's pre-kickoff
check of that match is done (entries_at_prekickoff; "trigger": "ki_check_done",
or "last_resort" half an hour before if the check did not finish). This script
still appends every version when run by hand.
"""
import argparse
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import log_store  # noqa: E402

LOG_PATH = log_store.LOGS / "combos"   # one file per competition
DEFAULT_API = "https://football-prediction.fly.dev"
COMPETITIONS = ("soccer_uefa_champs_league", "soccer_germany_bundesliga", "soccer_uefa_nations_league")
LEG_FIELDS = ("market", "outcome", "team", "best_odds", "bookmaker", "bookmaker_key",
              "home_team", "away_team", "commence_time",
              "market_probability", "probability", "conservative_probability", "model_probability", "ki_agrees")


def _kickoff(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def entries_due(report: dict, competition: str, now: datetime) -> list:
    """Tickets of both rules shown now: every one whose first leg has not yet
    kicked off."""
    out = []
    shown = report.get("policy") or "market"
    # The rule the page shows, and "agree" beside it. market, legacy_v3 and ki
    # are no longer logged (14 November); their old rows stay in the log.
    sources = [(shown, report.get("days") or [])]
    if report.get("agree_days") is not None:
        sources.append(("agree", report["agree_days"]))
    for policy, days in sources:
        for day in days:
            for option in day.get("by_size") or []:
                ticket = option.get("ticket")
                if not ticket:
                    continue
                first = min(_kickoff(l["commence_time"]) for l in ticket["legs"])
                if not now < first:
                    continue
                out.append({
                    "logged_at": now.isoformat(), "first_kickoff": first.isoformat(),
                    "date": day["date"], "competition": competition,
                    "policy": policy, "leg_count": ticket["leg_count"],
                    "combined_odds": ticket["combined_odds"],
                    "estimated_probability": ticket["conservative_probability"],
                    "model_probability": ticket["probability"],
                    "legs": [{k: l.get(k) for k in LEG_FIELDS} for l in ticket["legs"]],
                })
    return out


# The server logs a ticket once, shortly before its first match: when the AI's
# pre-kickoff check of that match is done (it runs in the hour before kickoff)
# - or, should that check not finish, half an hour before as a last resort.
PREKICKOFF_WINDOW = timedelta(hours=1)
LAST_RESORT = timedelta(minutes=30)


def entries_at_prekickoff(report: dict, competition: str, now: datetime, checked=None) -> list:
    """Tickets whose first match kicks off within the hour and whose AI check
    is done (`checked(first_leg)`), or within half an hour whatever happens."""
    out = []
    for e in entries_due(report, competition, now):
        left = _kickoff(e["first_kickoff"]) - now
        if left > PREKICKOFF_WINDOW:
            continue
        first_leg = min(e["legs"], key=lambda l: _kickoff(l["commence_time"]))
        if checked is not None and checked(first_leg):
            trigger = "ki_check_done"
        elif left <= LAST_RESORT:
            trigger = "last_resort"
        else:
            continue
        out.append({**e, "trigger": trigger})
    return out


def not_yet_logged(candidates: list, logged: list) -> list:
    """One entry per ticket slot and first kickoff: what was logged stands."""
    slot = lambda e: _key(e) + (e["first_kickoff"],)
    seen = {slot(e) for e in logged}
    out = []
    for e in candidates:
        if slot(e) not in seen:
            seen.add(slot(e))
            out.append(e)
    return out


def _key(e):
    """The slot a ticket fills: one rule's ticket of one size on one day."""
    # quote_basis is only in the oldest rows (not written since 14 November).
    return (e["date"], e["competition"], e["policy"], e["leg_count"],
            e.get("quote_basis", "single_book"))


def signature(e):
    """What makes a version: its legs, not their moving odds."""
    return tuple(sorted((l["home_team"], l["away_team"], l["market"], l.get("outcome") or "",
                         l.get("team") or "", l.get("bookmaker_key") or "")
                        for l in e["legs"]))


def new_versions(due: list, logged: list) -> list:
    """The tickets in `due` that differ from their slot's latest logged version."""
    latest = {}
    for e in logged:
        latest[_key(e)] = signature(e)
    out = []
    for e in due:
        if latest.get(_key(e)) != signature(e):
            latest[_key(e)] = signature(e)
            out.append(e)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)

    logged = log_store.load_combos()
    new = []
    for competition in COMPETITIONS:
        try:
            with urllib.request.urlopen(f"{args.api}/combo-ticket?competition={competition}", timeout=120) as r:
                report = json.loads(r.read())
        except Exception as exc:
            print(f"  {competition}: {type(exc).__name__}: {exc}")
            continue
        for entry in new_versions(entries_due(report, competition, now), logged + new):
            new.append(entry)
            print(f"  + {entry['date']} {entry['policy']:9} {entry['leg_count']}-fold @ {entry['combined_odds']}")

    if new:
        log_store.append_combos(new)
    print(f"{len(new)} neue Kombi(s) geloggt, {len(logged) + len(new)} insgesamt.")


if __name__ == "__main__":
    main()

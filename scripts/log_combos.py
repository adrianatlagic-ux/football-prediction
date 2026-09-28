"""Log the combo tickets the page shows - and the old rule's - before kickoff.

    python3 scripts/log_combos.py --api https://football-prediction.fly.dev

The combo rule changed on 26 September (market probabilities, legs from
1.30, no model filters). One winning ticket the evening before says nothing
either way, so both rules are logged on the same matches from now on and
compared once enough tickets have settled (scripts/grade_combos.py):

    market     the rule the page shows
    legacy_v3  the rule before: lower of model and market, model >= 55%,
               legs from 1.20, the model's warnings excluded

Every version the page shows is logged: whenever a rule's ticket of a size
changes its legs, the new version is appended with its time. A ticket
exists until its first leg kicks off - a started match leaves the combos -
so the last version logged is the one still placeable at kickoff, and each
earlier one is what the page showed in between. Odds moving on the same legs
do not make a new version.
"""
import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "combo_log.jsonl"
DEFAULT_API = "https://football-prediction.fly.dev"
COMPETITIONS = ("soccer_uefa_champs_league", "soccer_germany_bundesliga", "soccer_uefa_nations_league")
LEG_FIELDS = ("market", "outcome", "team", "best_odds", "home_team", "away_team", "commence_time",
              "market_probability", "probability", "conservative_probability")


def _kickoff(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def entries_due(report: dict, competition: str, now: datetime) -> list:
    """Tickets of both rules shown now: every one whose first leg has not yet
    kicked off."""
    out = []
    for policy, days in (("market", report.get("days") or []), ("legacy_v3", report.get("legacy_v3_days") or [])):
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


def _key(e):
    """The slot a ticket fills: one rule's ticket of one size on one day."""
    return (e["date"], e["competition"], e["policy"], e["leg_count"])


def signature(e):
    """What makes a version: its legs, not their moving odds."""
    return tuple(sorted((l["home_team"], l["away_team"], l["market"], l.get("outcome"), l.get("team"))
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

    logged = []
    if LOG_PATH.exists():
        logged = [json.loads(line) for line in LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
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
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            for entry in new:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"{len(new)} neue Kombi(s) geloggt, {len(logged) + len(new)} insgesamt.")


if __name__ == "__main__":
    main()

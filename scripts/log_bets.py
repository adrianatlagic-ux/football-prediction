"""Record EVERY match's full betting breakdown - not just the curated top pick -
so we can later check honestly how every tip the system ever considered performed.

Run this regularly, e.g. hourly (a match's odds can move a lot over the days
before kickoff, so a single run per day isn't enough - see FIRST_LOG_WINDOW_HOURS
below):

    python3 scripts/log_bets.py
    python3 scripts/log_bets.py --api https://football-prediction.fly.dev

It fetches the live /all-bets list (every match with odds, full breakdown -
exactly what the frontend's SmartBetCard shows). A match only gets its FIRST
log entry once it's within FIRST_LOG_WINDOW_HOURS of its own kickoff - logging
it days early would capture a stale pick that may bear no resemblance to what
was actually recommended right before kickoff. Once logged, an entry is
updated in place the first time its pre-kickoff movement ranking appears.
Matches with neither condition met are skipped, so running this repeatedly is
safe.

Grade the log later with scripts/grade_bets.py once matches have finished.
"""
import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "data" / "bet_log.jsonl"
DEFAULT_API = "https://football-prediction.fly.dev"


def _norm(name: str) -> str:
    import re
    n = re.sub(r"\band\b", " ", name.lower()).replace("&", " ")
    n = re.sub(r"[^a-z]", "", n)
    return {"usa": "unitedstates"}.get(n, n)


def _load_log(path=None) -> list:
    path = path or LOG_PATH
    entries = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return entries


def _has_movement(entry) -> bool:
    return bool((entry.get("combined") or {}).get("movement_ranking"))


def _fixture_key(entry) -> tuple:
    """Keep home/away rematches as separate observations in the audit log."""
    sport, event = entry.get("sport_key"), entry.get("event_id")
    if sport and event:
        return ("event", str(sport), str(event))
    return ("fixture", _norm(entry.get("home_team", "")), _norm(entry.get("away_team", "")),
            entry.get("commence_time"))


def _price_tip_upgrade(old, new) -> bool:
    """Whether a logged price tip should take a newer one: only when none was
    logged, or "no tip" was and a tip is now given."""
    if new is None:
        return False
    return old is None or (not old.get("tip") and bool(new.get("tip")))


def _build_entry(m, now):
    return {
        "logged_at": now,
        "home_team": m["home_team"],
        "away_team": m["away_team"],
        "commence_time": m.get("commence_time"),
        "event_id": m.get("event_id"),
        "sport_key": m.get("sport_key"),
        "recommendation": m.get("recommendation"),
        "recommendation_warning": m.get("recommendation_warning"),
        "green_bets": m.get("green_bets", []),
        "red_bets": m.get("red_bets", []),
        "agent_eval": m.get("agent_eval"),
        "model_favorite": m.get("model_favorite"),
        "safest_pick": m.get("safest_pick"),
        "likely_pick": m.get("likely_pick"),
        "odds_refreshed": m.get("odds_refreshed", False),
        "combined": m.get("combined"),
        # The price tip as shown: the tip or "no tip" with its reason, every
        # compared bet, and when Pinnacle's and bet-at-home's prices were read.
        "price_tip": m.get("price_tip"),
    }


# A match's FIRST log entry is only created within this many hours of its own
# kickoff - not days ahead. Logging the day-1 snapshot (whatever odds happen
# to exist when a match first appears in the feed, sometimes 2-3 days out)
# captured a pick that could be stale garbage by the time the match actually
# kicked off - see Belgium-Senegal, logged 2 days early as "Over 1.5" (would
# have won), while the pick that actually stood right before kickoff was a
# different bet that lost. Aligning the first log with the pre-kickoff
# odds-refresh window means the very first snapshot IS the near-kickoff one.
# 0.5h (30 min): the pre-kickoff agent re-check (research + Gemini call, both
# triggered up to 1h before kickoff) is reliably finished by 30 minutes out, so
# logging then captures the fully-settled pick including the movement ranking,
# not a still-in-progress one.
FIRST_LOG_WINDOW_HOURS = 0.5


def apply(matches, entries, now_dt):
    """Merge one /all-bets snapshot into the log entries. Returns (added, updated)."""
    now = now_dt.isoformat()
    by_key = {_fixture_key(e): e for e in entries}
    added = updated = 0
    for m in matches:
        new_entry = _build_entry(m, now)
        key = _fixture_key(new_entry)
        old = by_key.get(key)
        if old is None:
            commence = m.get("commence_time")
            hours_away = None
            if commence:
                try:
                    kickoff = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                    hours_away = (kickoff - now_dt).total_seconds() / 3600
                except ValueError:
                    pass
            if hours_away is None or hours_away > FIRST_LOG_WINDOW_HOURS:
                continue
            entries.append(new_entry)
            by_key[key] = new_entry
            added += 1
        elif _price_tip_upgrade(old.get("price_tip"), new_entry.get("price_tip")):
            # The first log can precede the last-hour read that decides the
            # tip: "no tip" then may become a tip. A tip once logged stands -
            # it is what the page showed - so only the empty side is filled.
            old["price_tip"] = new_entry["price_tip"]
            updated += 1
        elif not _has_movement(old) and _has_movement(new_entry):
            old.update(new_entry)
            updated += 1
    return added, updated


def write_log(entries, path=LOG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()
    data = json.load(urllib.request.urlopen(f"{args.api}/all-bets", timeout=60))
    entries = _load_log()
    added, updated = apply(data.get("all_bets", []), entries, datetime.now(timezone.utc))
    if added or updated:
        write_log(entries)
    print(f"{added} neu, {updated} aktualisiert. Log: {LOG_PATH} ({len(entries)} insgesamt).")


if __name__ == "__main__":
    main()

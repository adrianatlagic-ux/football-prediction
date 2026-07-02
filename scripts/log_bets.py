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


def _load_log() -> list:
    entries = []
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return entries


def _has_movement(entry) -> bool:
    return bool((entry.get("combined") or {}).get("movement_ranking"))


def _build_entry(m, now):
    return {
        "logged_at": now,
        "home_team": m["home_team"],
        "away_team": m["away_team"],
        "commence_time": m.get("commence_time"),
        "recommendation": m.get("recommendation"),
        "recommendation_warning": m.get("recommendation_warning"),
        "green_bets": m.get("green_bets", []),
        "red_bets": m.get("red_bets", []),
        "agent_eval": m.get("agent_eval"),
        "model_favorite": m.get("model_favorite"),
        "safest_pick": m.get("safest_pick"),
        "odds_refreshed": m.get("odds_refreshed", False),
        "combined": m.get("combined"),
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()

    data = json.load(urllib.request.urlopen(f"{args.api}/all-bets", timeout=60))
    matches = data.get("all_bets", [])

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()

    entries = _load_log()
    by_key = {(_norm(e["home_team"]), _norm(e["away_team"])): e for e in entries}

    added = updated = skipped_early = 0
    for m in matches:
        key = (_norm(m["home_team"]), _norm(m["away_team"]))
        new_entry = _build_entry(m, now)
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
                skipped_early += 1
                continue
            entries.append(new_entry)
            by_key[key] = new_entry
            added += 1
            tag = "+"
        elif not _has_movement(old) and _has_movement(new_entry):
            # The first (early-afternoon) snapshot had no movement ranking yet;
            # this later run near kickoff does. Upgrade the stored entry so the
            # log captures the movement-ranked pick the site actually showed at
            # kickoff - the whole reason a single 15:30 run kept missing it.
            old.update(new_entry)
            updated += 1
            tag = "~"
        else:
            continue
        rec = new_entry["recommendation"]
        rec_desc = f"{rec['market']} {rec.get('team') or rec['outcome']}" if rec else "no clean rec"
        mv = "  +movement" if _has_movement(new_entry) else ""
        print(f"  {tag} {m['home_team']} vs {m['away_team']}: {len(new_entry['green_bets'])} green bets, top={rec_desc}{mv}")

    if added or updated:
        with LOG_PATH.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"\n{added} neu, {updated} mit Movement-Ranking aktualisiert, "
          f"{skipped_early} noch zu früh (>{FIRST_LOG_WINDOW_HOURS}h vor Anpfiff, noch nicht geloggt). "
          f"Log: {LOG_PATH} ({len(entries)} insgesamt).")


if __name__ == "__main__":
    main()

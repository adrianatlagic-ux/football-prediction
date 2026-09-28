"""The server's own clock for the scheduled work.

GitHub Actions was meant to start the jobs, but its schedules ran every three
to four hours instead of hourly and skipped the daily run altogether; the
squad refresh for Germany-Greece fell into one of those gaps. The Fly machine
runs around the clock (min_machines_running = 1), so it now keeps the time
itself:

  every 10 minutes  squads/line-ups for matches kicking off within 75 min
                    (src/jobs.run_hourly - each match once), and the bet and
                    combo logs (the same rules as scripts/log_bets.py and
                    scripts/log_combos.py), written to data/logs/
  daily from 06:05  results, history, predictions for 48 hours, fixtures,
  UTC               morning odds (src/jobs.run_daily), once per day

The logs live on the server's disk until GitHub fetches them
(scripts/pull_server_logs.py) and commits them. Only started when
ENABLE_SCHEDULER=1 (set in fly.toml), so a local backend never spends
credits on its own.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "data" / "logs"
TICK_SECONDS = 600
DAILY_AFTER = (6, 5)
COMBO_COMPETITIONS = ("soccer_uefa_champs_league", "soccer_germany_bundesliga", "soccer_uefa_nations_league")

_started = False


def _daily_done_today(now: datetime) -> bool:
    from src.jobs import REPORTS
    try:
        report = json.loads((REPORTS / "last_daily.json").read_text(encoding="utf-8"))
        return (report.get("finished_at") or "")[:10] == now.date().isoformat()
    except (OSError, ValueError):
        return False


def log_bets_and_combos(all_bets, combo_ticket, now: datetime) -> dict:
    """The bet log and the combo log, kept on the server."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import log_bets
    import log_combos
    LOGS.mkdir(parents=True, exist_ok=True)
    bet_path = LOGS / "bet_log.jsonl"
    entries = log_bets._load_log(bet_path)
    added, updated = log_bets.apply(all_bets().get("all_bets", []), entries, now)
    if added or updated:
        log_bets.write_log(entries, bet_path)
    combo_path = LOGS / "combo_log.jsonl"
    logged = [json.loads(line) for line in combo_path.read_text(encoding="utf-8").splitlines()
              if line.strip()] if combo_path.exists() else []
    new = []
    for competition in COMBO_COMPETITIONS:
        due = log_combos.entries_due(combo_ticket(competition=competition), competition, now)
        new += log_combos.new_versions(due, logged + new)
    if new:
        with combo_path.open("a", encoding="utf-8") as fh:
            for entry in new:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"bets_added": added, "bets_updated": updated, "combos_added": len(new)}


def _loop(club, national, odds, all_bets, combo_ticket, real_results=None):
    from src import jobs
    while True:
        now = datetime.now(timezone.utc)
        try:
            if (now.hour, now.minute) >= DAILY_AFTER and not _daily_done_today(now):
                jobs.run_daily(club, national, odds, real_results)
        except Exception:
            pass
        try:
            jobs.run_hourly(club, national)
        except Exception:
            pass
        try:
            result = log_bets_and_combos(all_bets, combo_ticket, datetime.now(timezone.utc))
            jobs._report("logging", {"at": datetime.now(timezone.utc).isoformat(), **result})
        except Exception as exc:
            jobs._report("logging", {"at": datetime.now(timezone.utc).isoformat(),
                                     "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(TICK_SECONDS)


def start(club, national, odds, all_bets, combo_ticket, real_results=None) -> bool:
    global _started
    if _started or os.getenv("ENABLE_SCHEDULER") != "1":
        return False
    _started = True
    threading.Thread(target=_loop, args=(club, national, odds, all_bets, combo_ticket, real_results),
                     daemon=True, name="scheduler").start()
    return True

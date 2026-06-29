"""Record EVERY match's full betting breakdown - not just the curated top pick -
so we can later check honestly how every tip the system ever considered performed.

Run this regularly (e.g. once a day, after the daily odds refresh, before that
day's matches kick off):

    python3 scripts/log_bets.py
    python3 scripts/log_bets.py --api https://football-prediction.fly.dev

It fetches the live /all-bets list (every match with odds, full breakdown -
exactly what the frontend's SmartBetCard shows) and appends each NEW match to
data/bet_log.jsonl (one JSON object per line, append-only). Matches already in
the log are skipped, so running it repeatedly is safe - each match is captured
once, with the odds available at that moment, before they disappear once the
match finishes.

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


def _existing_keys() -> set:
    keys = set()
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                keys.add((_norm(e["home_team"]), _norm(e["away_team"])))
            except Exception:
                continue
    return keys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()

    data = json.load(urllib.request.urlopen(f"{args.api}/all-bets", timeout=60))
    matches = data.get("all_bets", [])
    existing = _existing_keys()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    with LOG_PATH.open("a", encoding="utf-8") as f:
        for m in matches:
            key = (_norm(m["home_team"]), _norm(m["away_team"]))
            if key in existing:
                continue
            entry = {
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
                "combined": m.get("combined"),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            existing.add(key)
            added += 1
            n_green = len(entry["green_bets"])
            rec = entry["recommendation"]
            rec_desc = f"{rec['market']} {rec.get('team') or rec['outcome']}" if rec else "no clean rec"
            print(f"  + {m['home_team']} vs {m['away_team']}: {n_green} green bets, top={rec_desc}")

    print(f"\n{added} neue(s) Spiel(e) protokolliert (komplette Wett-Aufschlüsselung). "
          f"Log: {LOG_PATH} ({len(existing)} insgesamt).")


if __name__ == "__main__":
    main()

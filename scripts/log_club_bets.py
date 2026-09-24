"""Record immutable pre-kickoff club tips, quoted odds and observed results."""
import argparse
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bet_audit import snapshot

ROOT = Path(__file__).resolve().parents[1] / "data"


def append_unique(path, rows, key):
    existing = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                existing.add(key(json.loads(line)))
    path.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with path.open("a") as stream:
        for row in rows:
            identity = key(row)
            if identity not in existing:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                existing.add(identity)
                added += 1
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="https://football-prediction.fly.dev")
    parser.add_argument("--out", type=Path, default=ROOT)
    args = parser.parse_args()
    append_unique(args.out / "club_bet_snapshots.jsonl", [], lambda r: r["snapshot_id"])
    append_unique(args.out / "club_results.jsonl", [], lambda r: "")
    errors = []
    try:
        payload = json.load(urllib.request.urlopen(f"{args.api}/all-bets", timeout=60))
        now = datetime.now(timezone.utc)  # Captured AFTER fetch; never backdate a slow request.
        entries, excluded = [], Counter()
        for match in payload.get("all_bets", []):
            entry, reason = snapshot(match, now)
            if reason:
                excluded[reason] += 1
            else:
                entries.append(entry)
        count = append_unique(args.out / "club_bet_snapshots.jsonl", entries, lambda r: r["snapshot_id"])
        print(f"New pre-match snapshots: {count}; exclusions: {dict(excluded)}")
    except Exception as exc:
        errors.append(f"Tip logging failed: {type(exc).__name__}")
    try:
        payload = json.load(urllib.request.urlopen(f"{args.api}/real-results", timeout=30))
        now = datetime.now(timezone.utc).isoformat()
        rows = [dict(r, observed_at=now) for r in payload.get("results", []) if r.get("completed")]
        key = lambda r: json.dumps({k: v for k, v in r.items() if k != "observed_at"}, sort_keys=True)
        count = append_unique(args.out / "club_results.jsonl", rows, key)
        print(f"New result observations: {count}")
    except Exception as exc:
        errors.append(f"Result logging failed: {type(exc).__name__}")
    if errors:
        raise SystemExit("; ".join(errors))


if __name__ == "__main__":
    main()

"""Fill the AI's memory for matches that are already logged and finished.

    GEMINI_API_KEY=... python3 scripts/build_match_memory.py              # all competitions
    GEMINI_API_KEY=... python3 scripts/build_match_memory.py --limit 20

Each finished tip with an AI pick gets one case in data/logs/memory/
(src/match_memory.py): ESPN facts plus a Gemini review with Google Search,
about 2 cents and 2 searches per match. Matches that already have a case are
skipped, so the script can be run again. The server does the same every day
for new matches (src/jobs.run_daily); this is for the backlog.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import log_store, match_memory  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    entries = log_store.load_tips()
    due = match_memory.due(entries, match_memory.load_cases())
    print(f"{len(due)} Spiele ohne Fall, analysiere bis zu {args.limit}")
    report = match_memory.update(entries, limit=args.limit, workers=args.workers)
    print(f"{report['added']} Fälle neu, {report['failed']} fehlgeschlagen")
    for err in report["errors"]:
        print("  " + err)


if __name__ == "__main__":
    main()

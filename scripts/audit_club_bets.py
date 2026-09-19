"""Settle real recorded pre-match tips; never backfill odds or predictions."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bet_audit import evaluate_snapshots

ROOT = Path(__file__).resolve().parents[1] / "data"


def read_rows(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", nargs="+", type=Path, default=[ROOT / "club_bet_snapshots.jsonl"])
    parser.add_argument("--results", type=Path, default=ROOT / "club_results.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "club_bet_performance.json")
    args = parser.parse_args()
    entries = [row for p in args.logs for row in read_rows(p)]
    results = read_rows(args.results)
    report = evaluate_snapshots(entries, results)
    report["comparison_basis"] = "Latest logged pre-match snapshot per fixture; see phase breakdown for final-only comparison"
    report["by_odds_stage"] = {}
    for stage in ("initial", "daily", "final", "untracked"):
        staged = [e for e in entries if (e.get("odds_stage") or "untracked") == stage]
        if staged:
            stage_report = evaluate_snapshots(staged, results)
            report["by_odds_stage"][stage] = {k: v for k, v in stage_report.items() if k != "settlements"}
    report["source_logs"] = [str(p) for p in args.logs]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({k:v for k,v in report.items() if k != "settlements"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

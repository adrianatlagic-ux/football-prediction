"""Grade the logged combo tickets and compare the two rules.

    python3 scripts/grade_combos.py
    python3 scripts/grade_combos.py --api https://football-prediction.fly.dev

For each rule and ticket size: tickets settled, how many landed, the hit
rate against the rule's own estimate, and the return at the logged odds.
Combos swing hard - a 3-fold lands about one time in three - so dozens of
tickets per rule are needed before a difference means anything; the report
says how many there are.
"""
import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade_bets import DEFAULT_API, _norm, grade  # noqa: E402

LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "combo_log.jsonl"


def settle(ticket: dict, finished: dict):
    """'win', 'loss' or None while any leg is unfinished (and none lost)."""
    outcomes = []
    for leg in ticket["legs"]:
        result = finished.get((_norm(leg["home_team"]), _norm(leg["away_team"])))
        outcomes.append(None if result is None else
                        grade(leg, leg["home_team"], leg["away_team"], result["home_score"], result["away_score"]))
    if "loss" in outcomes:
        return "loss"
    if all(o == "win" for o in outcomes):
        return "win"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()
    if not LOG_PATH.exists():
        print("Noch kein Kombi-Log. Erst scripts/log_combos.py laufen lassen.")
        return
    results = json.load(urllib.request.urlopen(f"{args.api}/real-results", timeout=60))["results"]
    finished = {(_norm(r["home_team"]), _norm(r["away_team"])): r
                for r in results if r.get("completed") and r.get("home_score") is not None}

    stats = defaultdict(lambda: {"n": 0, "won": 0, "units": 0.0, "expected": 0.0, "pending": 0})
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ticket = json.loads(line)
        s = stats[(ticket["policy"], ticket["leg_count"])]
        outcome = settle(ticket, finished)
        if outcome is None:
            s["pending"] += 1
            continue
        s["n"] += 1
        s["expected"] += ticket["estimated_probability"]
        if outcome == "win":
            s["won"] += 1
            s["units"] += ticket["combined_odds"] - 1
        else:
            s["units"] -= 1

    print(f"{'Regel':10} {'Größe':6} {'Tickets':>7} {'Treffer':>8} {'erwartet':>9} {'ROI':>8}  offen")
    for (policy, size), s in sorted(stats.items()):
        if s["n"]:
            print(f"{policy:10} {size}er    {s['n']:7} {s['won'] / s['n']:8.0%} {s['expected'] / s['n']:9.0%} "
                  f"{s['units'] / s['n']:+8.1%}  {s['pending']}")
        else:
            print(f"{policy:10} {size}er    {0:7} {'-':>8} {'-':>9} {'-':>8}  {s['pending']}")
    print("\nEin Unterschied zwischen den Regeln sagt erst bei Dutzenden abgerechneter Tickets je Regel etwas.")


if __name__ == "__main__":
    main()

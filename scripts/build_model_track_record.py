"""How often the model was right when it disagreed with the market.

    python3 scripts/build_model_track_record.py
    python3 scripts/build_model_track_record.py --api https://football-prediction.fly.dev

The page's ★ tip is the model's view where it departs most from the market.
Whether to follow it needs a measure, and the model's own confidence is not
one: it rated bets 60% that won 50%. This builds the measure from outcomes -
for each size of disagreement, how often such a bet actually won, set
against what the market and the model expected.

Two sources, kept apart in the output:
  archive  every Bundesliga 1X2 outcome 2021-22 to 2025-26 (except 2024-25,
           which has no archive), the model's point-in-time forecast against
           Pinnacle's pre-closing margin-free price
  live     every bet the site logged (data/bet_log.jsonl) with a model and a
           market probability, graded against the real result

Only outcomes the model rates ABOVE the market are counted - those are the
ones it would suggest. Writes data/model_track_record.json, which the API
serves and the ★ box reads.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data" / "model_track_record.json"
# Points by which the model rates a bet above the market.
BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.0)]


def bucket_of(gap: float):
    return next((b for b in BUCKETS if b[0] <= gap < b[1]), None)


# A verdict needs this many cases; fewer are reported as "too few".
MIN_CASES = 30


def verdict(cases: list) -> str:
    """'better', 'worse' or 'same' than the market expected, or 'too_few'.

    The number of wins is compared with the market's own expectation for
    exactly these bets (a sum of different probabilities, so its spread is
    the sum of p(1-p)); a difference counts beyond two standard deviations,
    about 95%.
    """
    if len(cases) < MIN_CASES:
        return "too_few"
    wins = sum(x["won"] for x in cases)
    expected = sum(x["market"] for x in cases)
    sd = sum(x["market"] * (1 - x["market"]) for x in cases) ** 0.5
    z = (wins - expected) / sd if sd else 0.0
    return "better" if z > 2 else "worse" if z < -2 else "same"


def summarise(cases: list) -> list:
    out = []
    for lo, hi in BUCKETS:
        c = [x for x in cases if lo <= x["gap"] < hi]
        n = len(c)
        out.append({"from": lo, "to": hi, "n": n, "verdict": verdict(c),
                    "hit_rate": round(sum(x["won"] for x in c) / n, 4) if n else None,
                    "market_expected": round(sum(x["market"] for x in c) / n, 4) if n else None,
                    "model_expected": round(sum(x["model"] for x in c) / n, 4) if n else None})
    return out


def archive_cases() -> list:
    from does_the_model_add_anything import load
    cases = []
    for r in load():
        for i in range(3):
            gap = r["model"][i] - r["pre"][i]
            if gap > 0:
                cases.append({"gap": gap, "won": r["result"] == i, "market": r["pre"][i], "model": r["model"][i]})
    return cases


def live_cases(api: str | None) -> list:
    path = ROOT / "data" / "bet_log.jsonl"
    if not api or not path.exists():
        return []
    from grade_bets import _norm, grade
    results = json.load(urllib.request.urlopen(f"{api}/real-results", timeout=60))["results"]
    finished = {(_norm(r["home_team"]), _norm(r["away_team"])): r
                for r in results if r.get("completed") and r.get("home_score") is not None}
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        res = finished.get((_norm(entry["home_team"]), _norm(entry["away_team"])))
        if not res:
            continue
        for b in entry.get("bets") or (entry.get("green_bets", []) + entry.get("red_bets", [])):
            model, market = b.get("model_probability_raw"), b.get("market_probability")
            if model is None or market is None or model <= market:
                continue
            g = grade(b, entry["home_team"], entry["away_team"], res["home_score"], res["away_score"])
            if g in ("win", "loss"):
                cases.append({"gap": model - market, "won": g == "win", "market": market, "model": model})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=None, help="to grade the live log against real results")
    args = parser.parse_args()
    archive = archive_cases()
    live = live_cases(args.api)
    report = {"buckets": [[lo, hi] for lo, hi in BUCKETS],
              "archive": summarise(archive), "live": summarise(live),
              "combined": summarise(archive + live),
              "sources": {"archive": "Bundesliga 1X2, model vs Pinnacle pre-closing, 2021-22..2025-26",
                          "live": "data/bet_log.jsonl, graded against /real-results"}}
    OUT.write_text(json.dumps(report, indent=1) + "\n")
    for label in ("archive", "live"):
        print(label)
        for b in report[label]:
            if b["n"]:
                print(f"  Modell {b['from']:.0%}-{b['to']:.0%} ueber Markt: n={b['n']:5}  getroffen {b['hit_rate']:.1%}  "
                      f"Markt erwartet {b['market_expected']:.1%}  Modell erwartet {b['model_expected']:.1%}  -> {b['verdict']}")
    print(f"geschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

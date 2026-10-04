"""Are bets where the model and the market agree the good ones?

    python3 scripts/agreement_test.py

A large gap between the model and the market turned out to be a model error
more often than a bargain. The mirror question: where the two agree within a
point or two, does the bet land more often than the market expects - is
agreement itself worth something?

Each bet is placed in a bucket by gap = model probability - market
probability, and each bucket's hit rate is set against the market's own
expectation (z beyond 2 is unlikely to be chance). Three sources:

  live     every bet the site logged for the Nations League, graded; the
           market is bet-at-home's margin-free price, the return is at its
           real odds (so the bookmaker's margin is in it)
  archive  Bundesliga 1X2, 2021-22 to 2025-26 (no 2024-25), the model's
           point-in-time forecast against Pinnacle's margin-free pre-closing
           price (scripts/does_the_model_add_anything.py)
  nations  Nations League 1X2, 2020-21 and 2024-25, national models trained
           before each season against the average German-licensed price
           (scripts/nl_backtest.py)

Writes data/model_reports/agreement_test_20261004.json.
"""
from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data" / "model_reports" / "agreement_test_20261004.json"
BUCKETS = [(-1.0, -0.10), (-0.10, -0.05), (-0.05, -0.02), (-0.02, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 1.0)]
LABELS = ["Modell >10 unter Markt", "5-10 darunter", "2-5 darunter", "±2 Punkte (einig)",
          "2-5 darüber", "5-10 darüber", "Modell >10 über Markt"]


def summarise(cases):
    out = []
    for (lo, hi), label in zip(BUCKETS, LABELS):
        c = [x for x in cases if lo <= x["gap"] < hi]
        n = len(c)
        if not n:
            out.append({"bucket": label, "n": 0})
            continue
        won = sum(x["won"] for x in c)
        exp = sum(x["market"] for x in c)
        sd = math.sqrt(sum(x["market"] * (1 - x["market"]) for x in c))
        row = {"bucket": label, "n": n, "hit": round(won / n, 3), "market_expected": round(exp / n, 3),
               "z": round((won - exp) / sd, 2) if sd else None}
        if all("odds" in x for x in c):
            row["roi"] = round(sum((x["odds"] - 1) if x["won"] else -1 for x in c) / n, 3)
        out.append(row)
    return out


def live_cases():
    from grade_bets import _norm, competition_of, grade
    results = json.load(urllib.request.urlopen("https://football-prediction.fly.dev/real-results", timeout=60))["results"]
    finished = {(_norm(r["home_team"]), _norm(r["away_team"]), str(r.get("commence_time"))[:10]): r
                for r in results if r.get("completed") and r.get("home_score") is not None}
    cases = []
    for line in (ROOT / "data" / "bet_log.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if competition_of(e) != "Nations League":
            continue
        r = finished.get((_norm(e["home_team"]), _norm(e["away_team"]), str(e.get("commence_time"))[:10]))
        if not r:
            continue
        for b in e.get("green_bets", []) + e.get("red_bets", []):
            model, market = b.get("model_probability_raw"), b.get("market_probability")
            if model is None or market is None:
                continue
            g = grade(b, e["home_team"], e["away_team"], r["home_score"], r["away_score"])
            if g in ("win", "loss"):
                cases.append({"gap": model - market, "market": market, "won": g == "win", "odds": b["best_odds"]})
    return cases


def archive_cases():
    from does_the_model_add_anything import load
    return [{"gap": r["model"][i] - r["pre"][i], "market": r["pre"][i], "won": r["result"] == i}
            for r in load() for i in range(3)]


def nations_cases():
    path = ROOT / "data" / "model_reports" / "nl_backtest_20260927" / "cases.jsonl"
    return [{"gap": c["model"] - c["market"], "market": c["market"], "won": c["won"]}
            for c in map(json.loads, path.read_text(encoding="utf-8").splitlines())]


def main():
    report = {"live": summarise(live_cases()), "archive": summarise(archive_cases()),
              "nations": summarise(nations_cases())}
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    for name, title in (("live", "LIVE Nations League (bet-at-home, mit Marge)"),
                        ("archive", "ARCHIV Bundesliga 1X2 (Pinnacle, ohne Marge)"),
                        ("nations", "BACKTEST Nations League 1X2 (Durchschnittsquote, ohne Marge)")):
        print(title)
        for row in report[name]:
            if row["n"]:
                roi = f"  ROI {row['roi']:+.0%}" if "roi" in row else ""
                print(f"  {row['bucket']:24} n={row['n']:5}  getroffen {row['hit']:.1%}  "
                      f"Markt erwartet {row['market_expected']:.1%}  z={row['z']:+.2f}{roi}")
        print()
    print(f"geschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

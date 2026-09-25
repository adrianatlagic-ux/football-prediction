"""Can slow bookmakers be beaten by pricing against a sharp one?

Every model-based selection in this project lost to random choice on closing-
line value. That ruled out knowing more than the market from our own numbers.
It did not rule out a different kind of edge, one that needs no football model:
bookmakers do not all move at the same speed. Pinnacle is widely treated as the
sharp price - low margin, high limits, fast to correct. If another book offers
more than Pinnacle's margin-free price for the same outcome, that is a pricing
error rather than an opinion, and backing it should beat the close.

    python3 scripts/pinnacle_edge_test.py

Method, fixed before looking at any result:
  - fair probability = Pinnacle's pre-closing 1X2, margin removed proportionally
  - bet an outcome when a price exceeds 1 / fair by more than the threshold
  - thresholds 0%, 2%, 5% - all three reported, none chosen afterwards
  - judged on closing-line value against Pinnacle's own margin-free close,
    which needs a tenth of the sample ROI does, and on ROI with a bootstrap
  - seasons 2021-22 and 2022-23 to look at, 2023-24 and 2025-26 held out

Two price sources: the best price across all listed books (what a bettor with
accounts everywhere could take) and Bet365 alone (what one ordinary account
gets). The first is optimistic - a "best" price is sometimes one book's stale
or erroneous quote that would be withdrawn or voided in practice.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DIRS = {"Bundesliga": ROOT / "data/odds_archive/football_data_20260923",
        "2. Bundesliga": ROOT / "data/odds_archive/football_data_d2_20260923"}
DEV = ("2122", "2223")
HOLD = ("2324", "2526")
THRESHOLDS = (0.0, 0.02, 0.05)
SOURCES = {"bester Preis": ("MaxH", "MaxD", "MaxA"), "nur Bet365": ("B365H", "B365D", "B365A")}
OUTCOMES = ("H", "D", "A")


def fair(prices):
    implied = [1 / p for p in prices]
    total = sum(implied)
    return [x / total for x in implied]


def number(row, key):
    try:
        value = float(row[key])
        return value if value > 1 else None
    except (KeyError, TypeError, ValueError):
        return None


def load():
    matches = []
    for league, folder in DIRS.items():
        for path in sorted(folder.glob("*.csv")):
            season = path.stem.split("_")[-1]
            for row in csv.DictReader(path.open(encoding="utf-8-sig", errors="ignore")):
                if not row.get("Date") or row.get("FTR") not in OUTCOMES:
                    continue
                pinnacle = [number(row, k) for k in ("PSH", "PSD", "PSA")]
                close = [number(row, k) for k in ("PSCH", "PSCD", "PSCA")]
                if None in pinnacle or None in close:
                    continue
                offers = {name: [number(row, k) for k in cols] for name, cols in SOURCES.items()}
                matches.append({"league": league, "season": season, "result": row["FTR"],
                                "fair": fair(pinnacle), "close_fair": fair(close), "offers": offers})
    return matches


def bets_for(matches, source, threshold):
    out = []
    for m in matches:
        prices = m["offers"][source]
        if None in prices:
            continue
        for i, outcome in enumerate(OUTCOMES):
            fair_odds = 1 / m["fair"][i]
            if prices[i] > fair_odds * (1 + threshold):
                won = m["result"] == outcome
                out.append({
                    "season": m["season"], "league": m["league"],
                    "profit": prices[i] - 1 if won else -1.0,
                    # Expected return against the sharp closing price: the
                    # low-noise verdict on whether the price was really wrong.
                    "clv": prices[i] * m["close_fair"][i] - 1,
                    "edge_at_bet": prices[i] * m["fair"][i] - 1,
                })
    return out


def summary(bets, rng):
    if not bets:
        return None
    profit = np.array([b["profit"] for b in bets])
    clv = np.array([b["clv"] for b in bets])
    boot = lambda a: np.percentile(a[rng.integers(0, len(a), (4000, len(a)))].mean(1), [2.5, 97.5])
    return {"bets": len(bets), "roi": float(profit.mean()), "roi_ci": [float(x) for x in boot(profit)],
            "clv": float(clv.mean()), "clv_ci": [float(x) for x in boot(clv)],
            "beat_close": float((clv > 0).mean()),
            "edge_claimed": float(np.mean([b["edge_at_bet"] for b in bets]))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "data/model_reports/pinnacle_edge_20260925.json")
    args = ap.parse_args()
    rng = np.random.default_rng(0)
    matches = load()
    print(f"{len(matches)} Spiele mit Pinnacle-Eroeffnung und -Schluss\n")

    report = {}
    for source in SOURCES:
        print(f"=== {source} ===")
        print(f"  {'Schwelle':>8} {'Split':>12} {'Wetten':>7} {'beansprucht':>12} {'CLV':>8} {'CLV 95%':>19} {'>Schluss':>9} {'ROI':>8} {'ROI 95%':>19}")
        for t in THRESHOLDS:
            all_bets = bets_for(matches, source, t)
            for split, seasons in (("Entwicklung", DEV), ("PRUEFUNG", HOLD)):
                s = summary([b for b in all_bets if b["season"] in seasons], rng)
                report[f"{source}|{t}|{split}"] = s
                if not s:
                    print(f"  {t:8.0%} {split:>12}       0"); continue
                print(f"  {t:8.0%} {split:>12} {s['bets']:7d} {s['edge_claimed']:+11.1%} "
                      f"{s['clv']:+7.2%} [{s['clv_ci'][0]:+6.2%},{s['clv_ci'][1]:+6.2%}] "
                      f"{s['beat_close']:8.0%} {s['roi']:+7.1%} [{s['roi_ci'][0]:+6.1%},{s['roi_ci'][1]:+6.1%}]")
        print()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"matches": len(matches), "results": report,
                                    "protocol": {"dev": DEV, "holdout": HOLD, "thresholds": THRESHOLDS}},
                                   indent=2) + "\n")
    print(f"geschrieben: {args.out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

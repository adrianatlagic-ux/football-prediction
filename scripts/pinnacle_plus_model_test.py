"""Does our model help choose among bets that beat Pinnacle's price?

The Pinnacle test found positive closing-line value from price alone: take a
bookmaker's quote when it exceeds Pinnacle's margin-free price. The obvious
next idea is to combine that with the model - prefer the gaps our model also
likes. This checks whether that helps before anyone builds it.

    python3 scripts/pinnacle_plus_model_test.py

The prior reason to doubt it: the selection research showed that the model's
disagreement with the market is anti-predictive. If "the model likes it" mostly
means "the model disagrees with Pinnacle", ranking by it would pick exactly the
cases where we have been most wrong.

Every Pinnacle-gap bet is split by what the model thinks relative to Pinnacle's
fair probability, and each group's closing-line value is compared. Bundesliga
only, because that is where archived model probabilities exist.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_bet_selection import ALIASES

ODDS = ROOT / "data/odds_archive/football_data_20260923"
DECISIONS = ROOT / "data/model_reports/selection_comparison_20260923/decisions.jsonl"
IDX = {"home_win": 0, "draw": 1, "away_win": 2}
FTR = {"home_win": "H", "draw": "D", "away_win": "A"}
THRESHOLD = 0.02


def fair(prices):
    implied = [1 / p for p in prices]
    return [x / sum(implied) for x in implied]


def num(row, key):
    try:
        v = float(row[key]); return v if v > 1 else None
    except (KeyError, TypeError, ValueError):
        return None


def load_odds():
    table = {}
    for path in sorted(ODDS.glob("D1_*.csv")):
        for r in csv.DictReader(path.open(encoding="utf-8-sig", errors="ignore")):
            if not r.get("Date"):
                continue
            d, m, y = r["Date"].split("/"); y = y if len(y) == 4 else "20" + y
            home = ALIASES.get(r["HomeTeam"].strip(), r["HomeTeam"].strip())
            away = ALIASES.get(r["AwayTeam"].strip(), r["AwayTeam"].strip())
            ps = [num(r, k) for k in ("PSH", "PSD", "PSA")]
            pc = [num(r, k) for k in ("PSCH", "PSCD", "PSCA")]
            mx = [num(r, k) for k in ("MaxH", "MaxD", "MaxA")]
            if None in ps + pc + mx or r.get("FTR") not in "HDA":
                continue
            table[(f"{y}-{m}-{d}", home, away)] = {"fair": fair(ps), "close": fair(pc),
                                                    "max": mx, "result": r["FTR"]}
    return table


def main():
    odds = load_odds()
    bets = []
    for row in (json.loads(l) for l in DECISIONS.open()):
        if row["scope"] != "1x2_preclosing":
            continue
        o = odds.get((row["date"], row["home"], row["away"]))
        if not o:
            continue
        for c in row["candidates"]:
            if c["outcome"] not in IDX:
                continue
            i = IDX[c["outcome"]]
            price, pin = o["max"][i], o["fair"][i]
            if price <= (1 / pin) * (1 + THRESHOLD):
                continue
            model = float(c["probability"])
            bets.append({"season": row["season"], "gap": price * pin - 1,
                         "model_minus_pinnacle": model - pin,
                         "clv": price * o["close"][i] - 1,
                         "profit": price - 1 if o["result"] == FTR[c["outcome"]] else -1.0})

    rng = np.random.default_rng(0)

    def show(label, group):
        if len(group) < 5:
            print(f"  {label:46} {len(group):4}  zu wenige"); return
        c = np.array([b["clv"] for b in group]); p = np.array([b["profit"] for b in group])
        ci = np.percentile(c[rng.integers(0, len(c), (4000, len(c)))].mean(1), [2.5, 97.5])
        print(f"  {label:46} {len(group):4}  CLV {c.mean():+6.2%} [{ci[0]:+.2%},{ci[1]:+.2%}]  ROI {p.mean():+6.1%}")

    print(f"{len(bets)} Wetten ueber Pinnacles fairer Quote (Schwelle {THRESHOLD:.0%}), mit Modellwert\n")
    show("alle - nur Preisvergleich", bets)
    print()
    show("Modell sieht es WAHRSCHEINLICHER als Pinnacle", [b for b in bets if b["model_minus_pinnacle"] > 0])
    show("Modell sieht es UNWAHRSCHEINLICHER als Pinnacle", [b for b in bets if b["model_minus_pinnacle"] <= 0])

    print("\n  Nach Fuenfteln der Modellmeinung (unten = Modell skeptisch, oben = Modell begeistert):")
    ranked = sorted(bets, key=lambda b: b["model_minus_pinnacle"])
    for k, chunk in enumerate(np.array_split(np.arange(len(ranked)), 5)):
        show(f"    Fuenftel {k + 1}", [ranked[j] for j in chunk])

    # The combination the user proposed: rank by price gap PLUS model edge,
    # take the top half, versus ranking by price gap alone.
    half = len(bets) // 2
    by_gap = sorted(bets, key=lambda b: -b["gap"])[:half]
    by_combo = sorted(bets, key=lambda b: -(b["gap"] + b["model_minus_pinnacle"]))[:half]
    print("\n  Obere Haelfte nach:")
    show("    nur Preisabstand", by_gap)
    show("    Preisabstand + Modellmeinung", by_combo)


if __name__ == "__main__":
    main()

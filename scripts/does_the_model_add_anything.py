"""Does our model know anything about a match that Pinnacle does not?

The price tip needs no model: it bets where a German bookmaker quotes above
Pinnacle's margin-free price. The model could only improve it by knowing
something about the outcome that Pinnacle's price has missed - so that is the
question to test, directly and with every match rather than a few dozen tips.

    python3 scripts/does_the_model_add_anything.py

The test: blend the two, p = (1 - w) * Pinnacle + w * model, and find the
weight w that predicts results best. If the model carries information the
market lacks, some w > 0 must lower the log-loss on unseen matches. If the
best weight is zero, the model adds nothing, whatever it is used for -
filter, veto, ranking or tie-break.

Two versions of "Pinnacle": the closing price, the market's final and best
estimate, and the pre-closing price, which is what exists when a bet is
actually placed. The model might anticipate the market sharpening between the
two even if it cannot beat the close.

Weight chosen on 2021-22 and 2022-23, judged on 2023-24 and 2025-26.

Finally, among bet-at-home's own price-tip opportunities, the tips are split
by what the model thinks - descriptively, because 46 bets decide nothing.
"""
from __future__ import annotations

import csv
import json
import sys
import unicodedata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_bet_selection import ALIASES

FD = ROOT / "data/odds_archive/football_data_20260923"
DECISIONS = ROOT / "data/model_reports/selection_comparison_20260923/decisions.jsonl"
OP = ROOT / "data/odds_archive/oddsportal_de_20260925/bundesliga_2324_2526_closing.json"
DEV, HOLD = ("2021-22", "2022-23"), ("2023-24", "2025-26")
IDX = {"home_win": 0, "draw": 1, "away_win": 2}


def fair(prices):
    inv = [1 / p for p in prices]
    return [x / sum(inv) for x in inv]


def load():
    archive = {}
    for path in sorted(FD.glob("D1_*.csv")):
        for r in csv.DictReader(path.open(encoding="utf-8-sig", errors="ignore")):
            try:
                pre = [float(r[k]) for k in ("PSH", "PSD", "PSA")]
                close = [float(r[k]) for k in ("PSCH", "PSCD", "PSCA")]
            except (KeyError, ValueError):
                continue
            d, m, y = r["Date"].split("/"); y = y if len(y) == 4 else "20" + y
            home = ALIASES.get(r["HomeTeam"].strip(), r["HomeTeam"].strip())
            away = ALIASES.get(r["AwayTeam"].strip(), r["AwayTeam"].strip())
            archive[(f"{y}-{m}-{d}", home, away)] = {
                "pre": fair(pre), "close": fair(close), "raw_home": r["HomeTeam"], "raw_away": r["AwayTeam"],
                "result": {"H": 0, "D": 1, "A": 2}[r["FTR"]]}
    rows = []
    for row in (json.loads(l) for l in DECISIONS.open()):
        if row["scope"] != "1x2_preclosing":
            continue
        a = archive.get((row["date"], row["home"], row["away"]))
        if not a:
            continue
        model = [None] * 3
        for c in row["candidates"]:
            if c["outcome"] in IDX:
                model[IDX[c["outcome"]]] = float(c["probability"])
        if None in model:
            continue
        total = sum(model)
        rows.append({**a, "date": row["date"], "season": row["season"],
                     "model": [x / total for x in model]})
    return rows


def logloss(rows, key, w):
    out = []
    for r in rows:
        p = (1 - w) * r[key][r["result"]] + w * r["model"][r["result"]]
        out.append(-np.log(max(p, 1e-12)))
    return np.array(out)


def blend_test(rows):
    dev = [r for r in rows if r["season"] in DEV]
    hold = [r for r in rows if r["season"] in HOLD]
    grid = np.round(np.arange(0, 1.0001, 0.05), 2)
    rng = np.random.default_rng(0)
    print(f"{len(dev)} Entwicklungs-, {len(hold)} Pruefspiele\n")
    for key, label in (("close", "Pinnacle Schlussquote"), ("pre", "Pinnacle vor Schluss (Zeitpunkt der Wette)")):
        dev_scores = [(logloss(dev, key, w).mean(), w) for w in grid]
        best = min(dev_scores)[1]
        base = logloss(hold, key, 0.0)
        mixed = logloss(hold, key, best)
        diff = mixed - base
        ci = np.percentile(diff[rng.integers(0, len(diff), (4000, len(diff)))].mean(1), [2.5, 97.5])
        model_only = logloss(hold, key, 1.0).mean()
        print(f"  gegen {label}:")
        print(f"    beste Modell-Beimischung (Entwicklung):  {best:.0%}")
        print(f"    Log-Loss Pruefjahre  Pinnacle allein {base.mean():.4f} | Mischung {mixed.mean():.4f} "
              f"| Modell allein {model_only:.4f}")
        print(f"    Verbesserung durch das Modell: {-diff.mean():+.4f}   95% [{-ci[1]:+.4f}, {-ci[0]:+.4f}]"
              f"   ({'hilft' if ci[1] < 0 else 'kein Nutzen'})\n")


def tokens(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return {w for w in s.replace(".", " ").replace("-", " ").split()
            if len(w) > 1 and w not in {"fc", "sc", "vfl", "vfb", "tsg", "sv", "1", "04", "05", "borussia",
                                        "bayer", "rb", "eintracht", "munich", "munchen"}}


def bet_at_home_split(rows):
    by_day = {}
    for r in rows:
        by_day.setdefault(r["date"], []).append(r)
    tips = []
    for m in json.load(OP.open()):
        cands = [r for r in by_day.get(m["startTime"][:10], [])
                 if tokens(r["raw_home"]) & tokens(m["homeTeam"]) and tokens(r["raw_away"]) & tokens(m["awayTeam"])]
        if len(cands) != 1:
            continue
        r = cands[0]
        b = next((b for b in m.get("bookmakerOdds", []) if b["bookmaker"] == "bet-at-home.de"), None)
        if not b:
            continue
        for i, side in enumerate(("home", "draw", "away")):
            price = b.get(side)
            if price and price * r["close"][i] - 1 > 0.02:
                tips.append({"model_gap": r["model"][i] - r["close"][i], "fair": r["close"][i],
                             "won": r["result"] == i, "price": price})
    print(f"  bet-at-home-Preistipps mit Modellwert: {len(tips)}  (beschreibend - zu wenige fuer einen Beweis)")
    for label, g in (("Modell sieht es WAHRSCHEINLICHER als Pinnacle", [t for t in tips if t["model_gap"] > 0]),
                     ("Modell sieht es UNWAHRSCHEINLICHER als Pinnacle", [t for t in tips if t["model_gap"] <= 0])):
        if not g:
            continue
        won = np.mean([t["won"] for t in g]); expected = np.mean([t["fair"] for t in g])
        roi = np.mean([t["price"] - 1 if t["won"] else -1 for t in g])
        print(f"    {label:48} {len(g):3}  gewonnen {won:5.1%} (erwartet {expected:5.1%})  ROI {roi:+6.1%}")


def main():
    rows = load()
    blend_test(rows)
    bet_at_home_split(rows)


if __name__ == "__main__":
    main()

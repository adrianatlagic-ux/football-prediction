"""Train the selector to beat the closing line instead of to make a profit.

Profit is a terrible training target here. A single bet returns -1 or a few
units, so a few hundred matches leave confidence intervals like -15% to
+14%: wide enough to hide any real effect and to invent one. That is why the
earlier selector runs decided so little.

Closing line value is the same question with far less noise. Taking a price
of 3.00 on something that closes at 2.70 is +11% whether or not the bet
happens to win, and the market's final price is the best public estimate
there is. Professionals judge a model this way for exactly this reason: it
needs roughly an order of magnitude fewer samples to reach a verdict.

    python3 scripts/clv_target_selector.py

Same protocol as before: develop on 2021-22 and 2022-23, report once on
2023-24 and 2025-26. 1X2 only, because football-data publishes no closing
handicap or totals. Prices are the best available across bookmakers, which
is what the live pipeline takes.

A positive out-of-sample CLV would be the first real sign of an edge in any
of these tests. Zero would mean the model cannot tell in advance which of
its own candidates the market will move toward.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_bet_selection import ALIASES

ODDS_DIR = ROOT / "data" / "odds_archive" / "football_data_20260923"
DECISIONS = ROOT / "data" / "model_reports" / "selection_comparison_20260923" / "decisions.jsonl"
SPREAD = ROOT / "data" / "model_reports" / "predictor_spread.jsonl"
DEV = ["2021-22", "2022-23"]
HOLD = ["2023-24", "2025-26"]
# Best price across books, opening and closing - what a line-shopper gets.
COLS = {"home_win": ("MaxH", "MaxCH"), "draw": ("MaxD", "MaxCD"), "away_win": ("MaxA", "MaxCA")}
IDX = {"home_win": 0, "draw": 1, "away_win": 2}


def load_odds(pattern="D1_*.csv"):
    table = {}
    for path in sorted(ODDS_DIR.glob(pattern)):
        for row in csv.DictReader(path.open(encoding="utf-8-sig", errors="ignore")):
            date = (row.get("Date") or "").strip()
            if not date:
                continue
            d, m, y = date.split("/")
            y = y if len(y) == 4 else "20" + y
            home = ALIASES.get((row.get("HomeTeam") or "").strip(), (row.get("HomeTeam") or "").strip())
            away = ALIASES.get((row.get("AwayTeam") or "").strip(), (row.get("AwayTeam") or "").strip())
            prices = {}
            for outcome, (pre, close) in COLS.items():
                try:
                    a, b = float(row[pre]), float(row[close])
                except (KeyError, TypeError, ValueError):
                    continue
                if a > 1 and b > 1:
                    prices[outcome] = (a, b)
            if len(prices) == 3:
                table[(f"{y}-{m}-{d}", home, away)] = prices
    return table


def devig(prices):
    implied = [1 / p for p in prices]
    return [v / sum(implied) for v in implied]


def build():
    odds = load_odds()
    spread = {(r["date"], r["home"], r["away"]): r
              for r in (json.loads(l) for l in SPREAD.open())} if SPREAD.exists() else {}
    matches = []
    for row in (json.loads(l) for l in DECISIONS.open()):
        if row["scope"] != "1x2_preclosing":
            continue
        key = (row["date"], row["home"], row["away"])
        if key not in odds:
            continue
        pre_probs = devig([odds[key][o][0] for o in COLS])
        s = spread.get(key)
        cands = []
        for c in row["candidates"]:
            outcome = c["outcome"]
            if outcome not in COLS:
                continue
            taken, closing = odds[key][outcome]
            i = IDX[outcome]
            p = float(c["probability"])
            q = pre_probs[i]
            feat = [p, q, p - q, np.log(taken), p * taken - 1,
                    float(c.get("suspicious", False)),
                    s["member_std"][i] if s else 0.0,
                    s["member_range"][i] if s else 0.0,
                    float(s["members_agree_argmax"]) if s else 0.0]
            cands.append({"x": feat, "clv": taken / closing - 1, "season": row["season"],
                          "outcome": outcome, "taken": taken, "closing": closing})
        if len(cands) == 3:
            matches.append(cands)
    return matches


NAMES = ["model_p", "market_q", "gap", "log_odds", "ev", "suspicious",
         "member_std", "member_range", "members_agree"]


def ridge(X, y, alpha):
    X = np.c_[np.ones(len(X)), np.asarray(X, float)]
    mu, sd = X[:, 1:].mean(0), X[:, 1:].std(0)
    sd[sd == 0] = 1
    X[:, 1:] = (X[:, 1:] - mu) / sd
    A = X.T @ X + alpha * np.eye(X.shape[1])
    A[0, 0] -= alpha
    return np.linalg.solve(A, X.T @ np.asarray(y, float)), mu, sd


def apply(model, X):
    w, mu, sd = model
    return np.c_[np.ones(len(X)), (np.asarray(X, float) - mu) / sd] @ w


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "data/model_reports/clv_target_20260923.json")
    args = ap.parse_args()

    matches = build()
    dev = [m for m in matches if m[0]["season"] in DEV]
    hold = [m for m in matches if m[0]["season"] in HOLD]
    print(f"{len(dev)} Entwicklungs-, {len(hold)} Holdout-Spiele (je 3 Kandidaten)")

    X = np.array([c["x"] for m in dev for c in m])
    y = np.array([c["clv"] for m in dev for c in m])
    print(f"CLV in den Entwicklungsdaten: Mittel {y.mean():+.2%}, Streuung {y.std():.2%}")

    rng = np.random.default_rng(0)
    idx = rng.permutation(len(X))
    folds = np.array_split(idx, 5)

    def cv(alpha):
        errs = []
        for f in folds:
            tr = np.setdiff1d(idx, f)
            if alpha is None:
                errs.append(np.mean((y[tr].mean() - y[f]) ** 2))
            else:
                errs.append(np.mean((apply(ridge(X[tr], y[tr], alpha), X[f]) - y[f]) ** 2))
        return float(np.mean(errs))

    mean_mse = cv(None)
    best_mse, best_a = min(((cv(a), a) for a in (1, 10, 50, 200, 1000, 5000, 20000)), key=lambda t: t[0])
    helps = best_mse < mean_mse
    print(f"\nMSE Mittelwert-Vorhersage {mean_mse:.6f} | bestes Modell {best_mse:.6f} (alpha={best_a})")
    print(f"  -> Merkmale sagen CLV {'VORHER' if helps else 'NICHT vorher'}")

    model = ridge(X, y, best_a)
    rows = []
    for name, group in (("Entwicklung", dev), ("HOLDOUT", hold)):
        picks = []
        for m in group:
            pred = apply(model, [c["x"] for c in m])
            picks.append(m[int(np.argmax(pred))])
        clv = np.array([p["clv"] for p in picks])
        sims = clv[rng.integers(0, len(clv), (4000, len(clv)))].mean(1)
        ci = [float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))]
        allc = np.array([c["clv"] for m in group for c in m])
        rows.append((name, len(picks), clv.mean(), (clv > 0).mean(), ci, allc.mean()))

    print(f"\n{'':14} {'Wetten':>7} {'CLV':>9} {'> Schluss':>11}  95%-Intervall        Zufallswahl")
    for name, n, mean, share, ci, rand in rows:
        print(f"  {name:12} {n:7d} {mean:+8.2%} {share:10.1%}  [{ci[0]:+.2%}, {ci[1]:+.2%}]  {rand:+.2%}")

    w = model[0]
    print("\n  Gewichte (standardisiert):")
    for nm, v in sorted(zip(NAMES, w[1:]), key=lambda t: -abs(t[1])):
        print(f"    {nm:16} {v:+.5f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "target": "closing_line_value", "protocol": {"dev": DEV, "holdout": HOLD, "alpha": best_a},
        "features_beat_mean_predictor": bool(helps),
        "mse_mean_predictor": mean_mse, "mse_best_model": best_mse,
        "results": [{"split": n, "bets": b, "mean_clv": float(m), "share_beating_close": float(s),
                     "ci95": c, "mean_clv_all_candidates": float(r)} for n, b, m, s, c, r in rows],
        "weights": dict(zip(NAMES, map(float, w[1:]))),
        "limits": ["1X2 only; no closing handicap or totals published",
                   "Best available price across books, both sides",
                   "Bundesliga only, retrospective"],
    }, indent=2) + "\n")
    print(f"\ngeschrieben: {args.out}")


if __name__ == "__main__":
    main()

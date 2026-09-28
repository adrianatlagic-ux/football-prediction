"""How much of the national prediction should come from the goal model?

    python3 scripts/nl_blend_test.py

The national prediction is (1 - w) * classifier + w * Poisson, w = 0.20. For
Belgium - France the classifier gave the home side 41% and France 30%
although France led on every measure; the Poisson part gave France 53%.
This tests w from 0 to 1 point-in-time, the same way as scripts/nl_backtest.py:
a model trained before each season, each match predicted with the history
up to the day before.

Two test sets per season:
  nations   the Nations League matches with a market price (OddsPortal),
            so each blend can also be set against the market
  all       every international played in the year after the cutoff -
            about five times as many matches, no market price

Differences are judged with a paired bootstrap over matches (2,000 draws):
a blend counts as better than 0.20 only if it is ahead in at least 95% of
them. Writes data/model_reports/nl_blend_test_20260928/summary.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from nl_backtest import SEASONS, odds_rows, train_until  # noqa: E402

OUT = ROOT / "data" / "model_reports" / "nl_blend_test_20260928"
WEIGHTS = [round(x, 1) for x in np.arange(0, 1.01, 0.1)]
CURRENT = 0.2


def parts(model, history, home, away):
    """Classifier and Poisson H/D/A for one match, as predict_match builds them."""
    from src.feature_engineering import build_prediction_row
    from src.poisson_model import predict_scorelines
    X = build_prediction_row(history, home, away, neutral=False)
    for col in model._feature_cols:
        if col not in X.columns:
            X[col] = 0.0
    clf = model.model.predict_proba(X[model._feature_cols])[0]
    po = predict_scorelines(history, home, away, is_knockout=False)
    return np.array(clf, dtype=float), np.array(
        [po["probability_home_win"], po["probability_draw"], po["probability_away_win"]], dtype=float)


def losses(rows, w):
    out = []
    for r in rows:
        p = (1 - w) * r["clf"] + w * r["poi"]
        p = p / p.sum()
        out.append(-np.log(max(p[r["result"]], 1e-12)))
    return np.array(out)


def bootstrap_share_better(a, b, draws=2000, seed=1):
    """Share of bootstrap samples in which loss a is below loss b."""
    rng = np.random.default_rng(seed)
    n = len(a)
    idx = rng.integers(0, n, size=(draws, n))
    return float(((a[idx].mean(axis=1)) < (b[idx].mean(axis=1))).mean())


def evaluate(rows, with_market):
    base = losses(rows, CURRENT)
    res = {"matches": len(rows), "by_weight": {}}
    for w in WEIGHTS:
        l = losses(rows, w)
        res["by_weight"][str(w)] = {"logloss": round(float(l.mean()), 4),
                                    "share_better_than_current": round(bootstrap_share_better(l, base), 3)}
    if with_market:
        m = np.array([-np.log(max(r["market"][r["result"]], 1e-12)) for r in rows])
        res["market_logloss"] = round(float(m.mean()), 4)
    return res


def main():
    from src.feature_engineering import encode_result
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    pooled = {"nations": [], "all": []}
    for season, cutoff in SEASONS.items():
        print(f"{season}: Modell bis {cutoff} trainieren ...", flush=True)
        model, everything = train_until(cutoff)
        everything = everything[everything["date"].dt.year >= 1990].copy()
        everything["result"] = [encode_result(h, a) for h, a in zip(everything["home_goals"], everything["away_goals"])]
        cut = pd.Timestamp(cutoff)

        nations = []
        for r in odds_rows(season):
            hist = everything[everything["date"] < pd.Timestamp(r["date"])].reset_index(drop=True)
            try:
                clf, poi = parts(model, hist, r["home"], r["away"])
            except Exception:
                continue
            nations.append({"clf": clf, "poi": poi, "result": r["result"], "market": r["market"]})

        year = everything[(everything["date"] >= cut) & (everything["date"] < cut + pd.DateOffset(years=1))]
        # Neutral-ground matches are left out: the site predicts home games.
        if "neutral" in year.columns:
            year = year[~year["neutral"].astype(str).str.upper().isin(["TRUE", "1"])]
        rows_all = []
        for _, m in year.iterrows():
            hist = everything[everything["date"] < m["date"]].reset_index(drop=True)
            try:
                clf, poi = parts(model, hist, m["home_team"], m["away_team"])
            except Exception:
                continue
            rows_all.append({"clf": clf, "poi": poi, "result": {"H": 0, "D": 1, "A": 2}[m["result"]]})
        print(f"  Nations League {len(nations)}, alle Laenderspiele {len(rows_all)}", flush=True)
        summary[season] = {"nations": evaluate(nations, True), "all": evaluate(rows_all, False)}
        pooled["nations"] += nations
        pooled["all"] += rows_all
    summary["pooled"] = {"nations": evaluate(pooled["nations"], True), "all": evaluate(pooled["all"], False)}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    for key, block in summary["pooled"].items():
        print(f"\n{key} (n={block['matches']})" + (f"  Markt {block['market_logloss']}" if "market_logloss" in block else ""))
        for w, v in block["by_weight"].items():
            print(f"  Poisson {float(w):.0%}: Log-Loss {v['logloss']}  besser als 20% in {v['share_better_than_current']:.0%}")
    print(f"geschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

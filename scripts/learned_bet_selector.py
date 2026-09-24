"""Does a LEARNED selector beat fixed rules at picking between a match's bets?

Every rule tested so far reorders candidates by a formula someone wrote down
(highest EV, highest hit rate, agreement with another label). None profited.
This asks a different question: can a small model learn FROM PAST MATCHES
when a computed edge was actually worth taking, and use that to choose among
the candidates of a single match?

Two ideas from the proposal are built in explicitly:

1. "Same tip" is not "supports this tip". A model that favours Denmark also
   supports Denmark +1.5, which an exact-match rule cannot see. The features
   below encode directional support instead of label equality.
2. Model's Choice, Safest and Value are not three votes. They are relabelled
   views of the same model numbers, so they contribute one signal, not three.

PROTOCOL, fixed before any result was looked at:
  develop on 2021-22 and 2022-23, report once on 2023-24 and 2025-26.
  No per-season rule picking, no revisiting the holdout after seeing it.

What this cannot answer: the AI research signal has no historical record
(pre-match analyses were never stored), and per-predictor spread inside the
ensemble was not archived either. Both are absent here by necessity, not by
choice, so a null result does not rule them out.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.bet_audit import settlement

DECISIONS = ROOT / "data" / "model_reports" / "selection_comparison_20260923" / "decisions.jsonl"
DEV_SEASONS = ["2021-22", "2022-23"]
HOLDOUT_SEASONS = ["2023-24", "2025-26"]


def market_family(market):
    if market == "1X2":
        return "1x2"
    if market.startswith("Handicap"):
        return "handicap"
    if market.startswith("Over/Under"):
        return "totals"
    return "other"


def model_favourite(candidates):
    """The team the model rates highest in the 1X2 market, if present."""
    ones = [c for c in candidates if c["market"] == "1X2" and c.get("team")]
    return max(ones, key=lambda c: c["probability"])["team"] if ones else None


def market_favourite(candidates):
    ones = [c for c in candidates if c["market"] == "1X2" and c.get("team")
            and isinstance(c.get("market_probability"), (int, float))]
    return max(ones, key=lambda c: c["market_probability"])["team"] if ones else None


def features(candidate, row):
    """One feature row per candidate.

    Directional support is the point of `backs_model_fav` / `backs_market_fav`:
    they are true when this bet is ON the side the model (or market) favours,
    whatever market it sits in - so a handicap on the favoured team counts as
    supported, which exact-label agreement would miss.
    """
    cands = row["candidates"]
    p = float(candidate["probability"])
    q = candidate.get("market_probability")
    q = float(q) if isinstance(q, (int, float)) else np.nan
    odds = float(candidate["best_odds"])
    fam = market_family(candidate["market"])
    team = candidate.get("team")
    mf, qf = model_favourite(cands), market_favourite(cands)

    return {
        "p": p,
        "odds": odds,
        "log_odds": np.log(odds),
        "ev": p * odds - 1,
        "q": q,
        "gap": p - q if not np.isnan(q) else 0.0,
        "has_market": 0.0 if np.isnan(q) else 1.0,
        "push": float(candidate.get("push_probability") or 0.0),
        "suspicious": float(bool(candidate.get("suspicious"))),
        "is_1x2": float(fam == "1x2"),
        "is_handicap": float(fam == "handicap"),
        "is_totals": float(fam == "totals"),
        "backs_model_fav": float(team is not None and team == mf),
        "backs_market_fav": float(team is not None and team == qf),
        "model_market_agree": float(mf is not None and mf == qf),
    }


FEATURE_ORDER = ["p", "odds", "log_odds", "ev", "q", "gap", "has_market", "push",
                 "suspicious", "is_1x2", "is_handicap", "is_totals",
                 "backs_model_fav", "backs_market_fav", "model_market_agree"]


def build(scope):
    rows = [json.loads(l) for l in DECISIONS.open()]
    out = []
    for r in rows:
        if r["scope"] != scope:
            continue
        match = []
        for c in r["candidates"]:
            try:
                _, units = settlement(c, r["home"], r["away"], r["home_goals"], r["away_goals"])
            except (ValueError, KeyError, TypeError):
                continue
            f = features(c, r)
            match.append({"x": [0.0 if np.isnan(f[k]) else f[k] for k in FEATURE_ORDER],
                          "profit": units, "season": r["season"], "date": r["date"],
                          "bet": c, "baseline": r["decisions"].get("kelly_baseline")})
        if match:
            out.append(match)
    return out


def fit_ridge(X, y, alpha):
    """Ridge regression in closed form; no dependency beyond numpy.

    Heavily regularised on purpose: a few hundred noisy matches will happily
    support a flexible model that finds an edge which is not there.
    """
    X = np.asarray(X, float)
    X = np.c_[np.ones(len(X)), X]
    mu, sd = X[:, 1:].mean(0), X[:, 1:].std(0)
    sd[sd == 0] = 1
    X[:, 1:] = (X[:, 1:] - mu) / sd
    A = X.T @ X + alpha * np.eye(X.shape[1])
    A[0, 0] -= alpha
    w = np.linalg.solve(A, X.T @ np.asarray(y, float))
    return w, mu, sd


def predict(model, X):
    w, mu, sd = model
    X = np.asarray(X, float)
    X = np.c_[np.ones(len(X)), (X - mu) / sd]
    return X @ w


def evaluate(matches, model, threshold):
    """Pick the best-predicted candidate per match, bet only above threshold."""
    profit, n, picks = 0.0, 0, []
    for m in matches:
        pred = predict(model, [c["x"] for c in m])
        best = int(np.argmax(pred))
        if pred[best] <= threshold:
            continue
        profit += m[best]["profit"]
        n += 1
        picks.append({"date": m[best]["date"], "bet": m[best]["bet"],
                      "predicted": float(pred[best]), "profit": m[best]["profit"]})
    return {"bets": n, "profit": profit, "roi": profit / n if n else 0.0, "picks": picks}


def baseline(matches):
    profit, n = 0.0, 0
    for m in matches:
        pick = m[0]["baseline"]
        if not pick:
            continue
        hit = next((c for c in m if c["bet"]["market"] == pick["market"]
                    and c["bet"]["outcome"] == pick["outcome"]
                    and c["bet"].get("team") == pick.get("team")), None)
        if hit:
            profit += hit["profit"]
            n += 1
    return {"bets": n, "profit": profit, "roi": profit / n if n else 0.0}


def bootstrap_roi(picks, draws=4000, seed=0):
    if not picks:
        return None
    rng = np.random.default_rng(seed)
    vals = np.array([p["profit"] for p in picks])
    sims = vals[rng.integers(0, len(vals), (draws, len(vals)))].mean(1)
    return [float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope", default="all_markets_preclosing")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    matches = build(args.scope)
    dev = [m for m in matches if m[0]["season"] in DEV_SEASONS]
    hold = [m for m in matches if m[0]["season"] in HOLDOUT_SEASONS]
    print(f"{args.scope}: {len(dev)} Entwicklungs-, {len(hold)} Holdout-Spiele")

    X = [c["x"] for m in dev for c in m]
    y = [c["profit"] for m in dev for c in m]

    # Alpha and threshold are chosen on development data only.
    best, chosen = None, None
    for alpha in (1, 10, 50, 200, 1000):
        model = fit_ridge(X, y, alpha)
        for thr in (0.0, 0.02, 0.05, 0.10):
            r = evaluate(dev, model, thr)
            if r["bets"] < 40:
                continue
            if best is None or r["roi"] > best["roi"]:
                best, chosen = r, (alpha, thr, model)
    if chosen is None:
        print("Keine Konfiguration mit genug Wetten auf den Entwicklungsdaten.")
        return
    alpha, thr, model = chosen
    print(f"auf Entwicklungsdaten gewaehlt: alpha={alpha}, Schwelle={thr}")
    print(f"  Entwicklung: {best['bets']} Wetten, ROI {best['roi']:+.1%}")

    dev_base, hold_base = baseline(dev), baseline(hold)
    hold_res = evaluate(hold, model, thr)
    ci = bootstrap_roi(hold_res["picks"])

    print()
    print(f"{'':28} {'Wetten':>7} {'Profit':>9} {'ROI':>8}")
    print(f"  {'Baseline Entwicklung':26} {dev_base['bets']:7d} {dev_base['profit']:+9.2f} {dev_base['roi']:+8.1%}")
    print(f"  {'Selektor Entwicklung':26} {best['bets']:7d} {best['profit']:+9.2f} {best['roi']:+8.1%}")
    print(f"  {'Baseline HOLDOUT':26} {hold_base['bets']:7d} {hold_base['profit']:+9.2f} {hold_base['roi']:+8.1%}")
    print(f"  {'Selektor HOLDOUT':26} {hold_res['bets']:7d} {hold_res['profit']:+9.2f} {hold_res['roi']:+8.1%}")
    if ci:
        print(f"  95%-Intervall Selektor HOLDOUT: {ci[0]:+.1%} bis {ci[1]:+.1%}")

    w = model[0]
    print("\n  Gewichte (standardisiert), groesste zuerst:")
    for name, val in sorted(zip(FEATURE_ORDER, w[1:]), key=lambda t: -abs(t[1]))[:6]:
        print(f"    {name:20} {val:+.4f}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "scope": args.scope, "protocol": {"dev": DEV_SEASONS, "holdout": HOLDOUT_SEASONS,
                                              "alpha": alpha, "threshold": thr},
            "development": {"baseline": dev_base, "selector": {k: best[k] for k in ("bets", "profit", "roi")}},
            "holdout": {"baseline": hold_base,
                        "selector": {k: hold_res[k] for k in ("bets", "profit", "roi")},
                        "roi_ci95": ci},
            "weights": dict(zip(FEATURE_ORDER, map(float, w[1:]))),
            "limits": [
                "Retrospective; not archived live tips",
                "No historical AI research or per-predictor spread available",
                "Bundesliga only, single bookmaker",
                "Holdout reported once; alpha and threshold fixed on development data",
            ],
        }, indent=2) + "\n")
        print(f"\ngeschrieben: {args.out}")


if __name__ == "__main__":
    main()

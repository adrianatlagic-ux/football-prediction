"""Honest evaluation: does our model actually beat the market?

For every graded candidate bet we have BOTH the model's probability and the
devig'd market probability, plus the real outcome. That lets us score the two
forecasters head to head:

- Brier score = mean( (probability - outcome)^2 ), outcome 1=win/0=loss.
  Lower is better. If the MARKET's Brier is lower than the MODEL's, the model
  has no edge - we'd literally be better off just trusting the bookmaker.
- Calibration buckets: of the bets the model rated e.g. 60-70% likely, what
  share actually won? Well-calibrated = actual hit rate lands inside the bucket.

Run:  python3 scripts/evaluate_model.py
      python3 scripts/evaluate_model.py --api https://football-prediction.fly.dev

This reuses grade_bets.grade() so the win/loss logic stays identical.
"""
import argparse
import json
import urllib.request
from pathlib import Path

from grade_bets import grade, _norm

LOG_PATH = Path(__file__).parent.parent / "data" / "bet_log.jsonl"
DEFAULT_API = "https://football-prediction.fly.dev"


def brier(samples):
    """samples = list of (prob, outcome01). Returns (brier, n)."""
    if not samples:
        return None, 0
    return sum((p - o) ** 2 for p, o in samples) / len(samples), len(samples)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=DEFAULT_API)
    args = parser.parse_args()

    results = json.load(urllib.request.urlopen(f"{args.api}/real-results", timeout=30))["results"]
    finished = {}
    for r in results:
        if r.get("completed") and r.get("home_score") is not None:
            finished[(_norm(r["home_team"]), _norm(r["away_team"]))] = r

    model_samples = []   # (model_prob, outcome01)
    market_samples = []  # (market_prob, outcome01) - only where we have a market prob
    paired = []          # (model_prob, market_prob, outcome01) - both available
    buckets = {i: [0, 0] for i in range(5, 10)}  # 50-59,60-69,...,90-99 -> [wins, total]

    n_matches = 0
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        home, away = entry["home_team"], entry["away_team"]
        res = finished.get((_norm(home), _norm(away)))
        if res is None:
            continue
        n_matches += 1
        hs, as_ = res["home_score"], res["away_score"]

        seen = set()
        for b in entry.get("green_bets", []) + entry.get("red_bets", []):
            key = (b["market"], b["outcome"], b.get("team"))
            if key in seen:
                continue
            seen.add(key)
            g = grade(b, home, away, hs, as_)
            if g not in ("win", "loss"):
                continue  # skip pushes / ungradeable
            o = 1.0 if g == "win" else 0.0
            mp = b.get("probability")
            kp = b.get("market_probability")
            if mp is not None:
                model_samples.append((mp, o))
                bucket = min(9, max(5, int(mp * 10)))
                buckets[bucket][0] += int(o)
                buckets[bucket][1] += 1
            if mp is not None and kp is not None:
                market_samples.append((kp, o))
                paired.append((mp, kp, o))

    print(f"Matches evaluated: {n_matches}")
    print(f"Gradeable candidate bets (model): {len(model_samples)}")
    print(f"  ...with a market probability too: {len(paired)}\n")

    mb, mn = brier(model_samples)
    if mb is not None:
        print(f"Model Brier score:  {mb:.4f}  (n={mn})")

    # Fair head-to-head: only on the bets where BOTH have a probability.
    if paired:
        model_paired = brier([(m, o) for m, k, o in paired])[0]
        market_paired = brier([(k, o) for m, k, o in paired])[0]
        print(f"\nHead-to-head on the {len(paired)} bets where both gave a probability:")
        print(f"  Model Brier:   {model_paired:.4f}")
        print(f"  Market Brier:  {market_paired:.4f}")
        if model_paired < market_paired:
            print(f"  -> Model is better calibrated by {market_paired - model_paired:.4f}. Possible edge.")
        else:
            print(f"  -> MARKET is better by {model_paired - market_paired:.4f}. No demonstrated edge.")
        # A constant 'always predict the base rate' baseline for reference.
        base = sum(o for m, k, o in paired) / len(paired)
        base_brier = brier([(base, o) for m, k, o in paired])[0]
        print(f"  (Baseline 'always {base:.0%}' Brier: {base_brier:.4f} - any real forecaster should beat this)")

    print("\nModel calibration buckets (model said X%, actually won Y%):")
    for i in range(5, 10):
        wins, total = buckets[i]
        if total:
            print(f"  {i*10}-{i*10+9}% predicted -> {wins}/{total} won ({wins/total:.0%} actual)")
        else:
            print(f"  {i*10}-{i*10+9}% predicted -> no bets")

    print("\nNOTE: sample is small - treat as directional, not proof. "
          "Re-run as more matches finish (logging is now automated daily).")


if __name__ == "__main__":
    main()

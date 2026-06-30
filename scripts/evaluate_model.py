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

    def market_group(market):
        if market.startswith("Over/Under"):
            return "Over/Under"
        if market.startswith("Handicap"):
            return "Handicap"
        return "1X2"

    model_samples = []   # (model_prob, outcome01)
    paired = []          # (model_prob, market_prob, outcome01) - both available
    buckets = {i: [0, 0] for i in range(5, 10)}  # 50-59,60-69,...,90-99 -> [wins, total]
    # Same, but split per market group, so we can see if Over/Under (the
    # Poisson goals model - our weakest part) is worse than 1X2.
    by_group = {}  # group -> {"paired": [...], "buckets": {5:[0,0],...}}

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
            # Always evaluate the RAW model probability (pre market-blend), so
            # the calibration verdict is about the model itself regardless of
            # whether the entry was logged before or after the blend was added.
            mp = b.get("model_probability_raw", b.get("probability"))
            kp = b.get("market_probability")
            if mp is None:
                continue
            model_samples.append((mp, o))
            bucket = min(9, max(5, int(mp * 10)))
            buckets[bucket][0] += int(o)
            buckets[bucket][1] += 1

            grp = by_group.setdefault(market_group(b["market"]),
                                      {"paired": [], "buckets": {i: [0, 0] for i in range(5, 10)}})
            grp["buckets"][bucket][0] += int(o)
            grp["buckets"][bucket][1] += 1
            if kp is not None:
                paired.append((mp, kp, o))
                grp["paired"].append((mp, kp, o))

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

    print("\n=== Per-market breakdown (is Over/Under really the weak spot?) ===")
    for grp in ("1X2", "Over/Under", "Handicap"):
        g = by_group.get(grp)
        if not g:
            print(f"\n{grp}: no graded bets yet")
            continue
        gp = g["paired"]
        print(f"\n{grp}: {sum(t for _, t in g['buckets'].values())} graded bets")
        if gp:
            mB = brier([(m, o) for m, k, o in gp])[0]
            kB = brier([(k, o) for m, k, o in gp])[0]
            verdict = "model better" if mB < kB else "MARKET better"
            print(f"  Model Brier {mB:.4f} vs Market Brier {kB:.4f}  -> {verdict}")
        for i in range(5, 10):
            wins, total = g["buckets"][i]
            if total:
                flag = ""
                # Overconfident = predicted bucket midpoint well above actual.
                if wins / total < i / 10:
                    flag = "  <-- overconfident"
                print(f"  {i*10}-{i*10+9}% -> {wins}/{total} won ({wins/total:.0%}){flag}")

    print("\nNOTE: sample is small - treat as directional, not proof. "
          "Re-run as more matches finish (logging is now automated daily).")


if __name__ == "__main__":
    main()

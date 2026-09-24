"""Recover per-predictor probabilities the stored predictions never kept.

data/model_reports/retraining_v3/predictions.jsonl holds only the blended
ensemble output, so "does this edge rest on agreement or on one outlier?"
could not be answered - the one input the selection proposal names that was
neither tested nor genuinely impossible to obtain.

The ensemble is RF + XGBoost + CatBoost behind a fixed recipe, so the same
chronological fits can be repeated and each member's probabilities recorded
alongside the blend. Same policy, same cutoffs and same seasons as the run
that produced predictions.jsonl, so the output lines up match for match.

    python3 scripts/reconstruct_predictor_spread.py --out data/model_reports/predictor_spread.jsonl

This re-fits models rather than reading a cache; expect several minutes.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.club_backtest import CalibratedClubModel, poisson_for_dates
from src.club_data_loader import load_completed_matches
from src.club_features_v3 import build_features, prepare_history
from src.club_market_value_policy import MarketValueHistory

SEASONS = ["2021-22", "2022-23", "2023-24", "2025-26"]
POLICY = "verified_only"   # matches the stored predictions, not today's default
ORDER = ["H", "D", "A"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "data/model_reports/predictor_spread.jsonl")
    args = ap.parse_args()

    history = prepare_history(load_completed_matches())
    market = MarketValueHistory()
    print(f"{len(history)} Spiele geladen", flush=True)

    print("Baue Features...", flush=True)
    X = build_features(history, POLICY, market)

    needed = history[history.date >= "2020-01-01"]
    print(f"Poisson-Kontexte fuer {len(needed)} Spiele...", flush=True)
    scores = poisson_for_dates(history, needed)
    pp = np.full((len(history), 3), np.nan)
    keys = ["probability_home_win", "probability_draw", "probability_away_win"]
    for idx, s in scores.items():
        pp[idx] = [s[k] for k in keys]

    out = []
    for season in SEASONS:
        fixtures = history[(history.season == season) & (history.competition == "bundesliga")]
        if fixtures.empty:
            continue
        cutoff = fixtures.date.min()
        print(f"{season}: fit < {cutoff.date()}, {len(fixtures)} Spiele", flush=True)
        bundle = CalibratedClubModel().fit(history, X, cutoff, pp)

        Xs = X.loc[fixtures.index, bundle.feature_columns]
        # Each ensemble member on its own, then the blend they actually form.
        members = {}
        for predictor in bundle.model.predictors:
            name = type(predictor).__name__.replace("Predictor", "")
            members[name] = predictor.predict_proba(Xs)
        raw, _ = bundle.predict(Xs, pp[fixtures.index])

        for i, r in enumerate(fixtures.itertuples()):
            per = {n: [float(v) for v in probs[i]] for n, probs in members.items()}
            stacked = np.array([probs[i] for probs in members.values()])
            out.append({
                "season": season, "date": str(r.date.date()),
                "home": r.home_team, "away": r.away_team, "actual": r.result,
                "ensemble": [float(v) for v in raw[i]],
                "members": per,
                # Spread of the members around each outcome: small means they
                # agree, large means the blend is carried by one of them.
                "member_std": [float(v) for v in stacked.std(axis=0)],
                "member_range": [float(v) for v in (stacked.max(axis=0) - stacked.min(axis=0))],
                "members_agree_argmax": bool(len({int(p.argmax()) for p in stacked}) == 1),
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        for row in out:
            fh.write(json.dumps(row) + "\n")
    print(f"\n{len(out)} Zeilen -> {args.out}", flush=True)
    agree = sum(r["members_agree_argmax"] for r in out)
    print(f"Einzelmodelle einig ueber den Favoriten: {agree}/{len(out)} ({agree/len(out):.0%})", flush=True)


if __name__ == "__main__":
    main()

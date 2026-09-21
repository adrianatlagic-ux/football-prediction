"""Walk-forward comparison of the three market-value availability policies.

The three policies differ only in what they assume was publicly known before
a match, which is exactly the disputed point:

  verified_only   only rows carrying an availability date. Our history has
                  none, so every market-value feature is constant - in
                  effect, no market values at all.
  lagged_season   the PREVIOUS season's value, assumed known by 1 July.
                  Conservative: a figure labelled for a finished season was
                  certainly published before the new one started.
  current_season  the CURRENT season's value (the July heuristic we shipped
                  earlier). More informative if those figures really were
                  set at season start - but a Transfermarkt figure labelled
                  "2023" may be a May 2024 snapshot, in which case this
                  leaks the future into an October 2023 match.

Everything else is held identical: same fixtures, same chronological fits,
same ensemble, same Poisson contexts. Only the policy varies, so any
difference is attributable to it.

A better score for current_season would NOT by itself prove the policy is
sound - leakage improves scores too. Read it the other way round: if
current_season is not clearly better, the aggressive assumption buys nothing
and the conservative policy should win on principle.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.club_backtest import CalibratedClubModel, poisson_for_dates, probabilities_metrics
from src.club_data_loader import load_completed_matches
from src.club_features_v3 import build_features, prepare_history
from src.club_market_value_policy import MarketValueHistory

POLICIES = ["verified_only", "lagged_season", "current_season"]
SEASONS = ["2021-22", "2022-23", "2023-24", "2025-26"]
COMPETITIONS = ["bundesliga", "champions_league"]


def paired_log_loss_test(rows_a, rows_b):
    """Per-match log-loss difference with a normal-approximation z score.

    The same fixtures are scored by both policies, so the comparison is
    paired; an unpaired summary would overstate the noise.
    """
    a = np.array([r["log_loss_match"] for r in rows_a])
    b = np.array([r["log_loss_match"] for r in rows_b])
    if len(a) != len(b) or not len(a):
        return None
    diff = a - b
    se = diff.std(ddof=1) / np.sqrt(len(diff))
    return {
        "n": int(len(diff)),
        "mean_difference": float(diff.mean()),
        "std_error": float(se),
        "z": float(diff.mean() / se) if se > 0 else None,
        "note": "negative mean favours the first policy",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/model_reports/market_value_policies"))
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("Choose a new report directory; historical evaluations are immutable")
    args.out.mkdir(parents=True)

    history = prepare_history(load_completed_matches())
    market = MarketValueHistory()
    print(f"{len(history)} matches loaded", flush=True)

    features = {}
    for policy in POLICIES:
        print(f"Building features: {policy}", flush=True)
        features[policy] = build_features(history, policy, market)

    needed = history[history.date >= "2020-01-01"]
    print(f"Poisson contexts for {len(needed)} matches", flush=True)
    scores = poisson_for_dates(history, needed)
    pp = np.full((len(history), 3), np.nan)
    keys = ["probability_home_win", "probability_draw", "probability_away_win"]
    for idx, score in scores.items():
        pp[idx] = [score[k] for k in keys]

    index = {"H": 0, "D": 1, "A": 2}
    rows = []
    for season in SEASONS:
        fixtures = history[(history.season == season) & history.competition.isin(COMPETITIONS)]
        if fixtures.empty:
            continue
        cutoff = fixtures.date.min()
        for policy in POLICIES:
            print(f"{season} {policy}: fit < {cutoff.date()}, {len(fixtures)} fixtures", flush=True)
            bundle = CalibratedClubModel().fit(history, features[policy], cutoff, pp)
            raw, _ = bundle.predict(features[policy].loc[fixtures.index], pp[fixtures.index])
            probs = np.clip(raw, 1e-12, 1)
            probs = probs / probs.sum(axis=1, keepdims=True)
            for i, fixture in enumerate(fixtures.itertuples()):
                actual = index[fixture.result]
                rows.append({
                    "season": season, "competition": fixture.competition, "policy": policy,
                    "date": str(fixture.date.date()), "home": fixture.home_team, "away": fixture.away_team,
                    "actual": fixture.result, "probabilities": probs[i].tolist(),
                    "log_loss_match": float(-np.log(probs[i][actual])),
                })
            with (args.out / "predictions.jsonl").open("a") as stream:
                for row in rows[-len(fixtures):]:
                    stream.write(json.dumps(row, allow_nan=False) + "\n")

    frame = pd.DataFrame(rows)
    results = []
    for (policy, competition), group in frame.groupby(["policy", "competition"]):
        results.append({"policy": policy, "competition": competition,
                        **probabilities_metrics(group.actual, np.array(group.probabilities.tolist()))})
    overall = []
    for policy, group in frame.groupby("policy"):
        overall.append({"policy": policy,
                        **probabilities_metrics(group.actual, np.array(group.probabilities.tolist()))})

    by_policy = {p: [r for r in rows if r["policy"] == p] for p in POLICIES}
    tests = {
        "lagged_season_vs_verified_only": paired_log_loss_test(by_policy["lagged_season"], by_policy["verified_only"]),
        "current_season_vs_verified_only": paired_log_loss_test(by_policy["current_season"], by_policy["verified_only"]),
        "current_season_vs_lagged_season": paired_log_loss_test(by_policy["current_season"], by_policy["lagged_season"]),
    }

    (args.out / "results.json").write_text(json.dumps(
        {"overall": overall, "by_competition": results, "paired_tests": tests,
         "market_value_audit": market.audit(),
         "protocol": {"seasons": SEASONS, "competitions": COMPETITIONS,
                      "schedule": "season-frozen fit, identical across policies",
                      "treatment": "raw (uncalibrated) probabilities"},
         "limitations": [
             "2025/26 and earlier seasons were used in previous experiments; not an untouched sample",
             "A better score for current_season would not prove its availability assumption - leakage improves scores too",
             "No historical bookmaker odds, so no profitability conclusion follows from any of this",
         ]}, indent=2, allow_nan=False) + "\n")

    lines = ["# Market-value policy comparison", "",
             "| Policy | n | Accuracy | Log loss | Brier |", "|---|---:|---:|---:|---:|"]
    for r in sorted(overall, key=lambda x: x["log_loss"]):
        lines.append(f"| {r['policy']} | {r['n']} | {r['accuracy']:.1%} | {r['log_loss']:.4f} | {r['brier']:.4f} |")
    lines += ["", "| Policy | Competition | n | Accuracy | Log loss | Brier |", "|---|---|---:|---:|---:|---:|"]
    for r in sorted(results, key=lambda x: (x["competition"], x["log_loss"])):
        lines.append(f"| {r['policy']} | {r['competition']} | {r['n']} | {r['accuracy']:.1%} | {r['log_loss']:.4f} | {r['brier']:.4f} |")
    lines += ["", "## Paired log-loss tests", "",
              "| Comparison | n | Mean difference | z |", "|---|---:|---:|---:|"]
    for name, test in tests.items():
        if test:
            z = f"{test['z']:.2f}" if test["z"] is not None else "-"
            lines.append(f"| {name} | {test['n']} | {test['mean_difference']:+.4f} | {z} |")
    lines += ["", "Negative mean difference favours the first policy. |z| below ~2 is not",
              "distinguishable from noise at this sample size.", "",
              "A better score for `current_season` would not establish that its availability",
              "assumption holds - leakage also improves scores. The useful reading is the",
              "reverse: if it is not clearly better, the aggressive assumption buys nothing."]
    (args.out / "README.md").write_text("\n".join(lines) + "\n")
    print(f"Complete: {args.out}", flush=True)


if __name__ == "__main__":
    main()

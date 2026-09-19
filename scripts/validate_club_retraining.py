"""Season-frozen vs monthly-refitted club models, reported by competition.

No current odds or simulated betting returns are used. The 2025/26 season
has been examined before; this is a retrospective check, not fresh proof.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.club_data_loader import load_completed_matches, RAW_PATH
from src.club_features_v3 import prepare_history, build_features
from src.club_market_value_policy import MarketValueHistory
from src.club_backtest import CalibratedClubModel, poisson_for_dates, probabilities_metrics


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/model_reports/retraining_v3"))
    parser.add_argument("--save-model", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("Choose a new report directory; historical evaluations are immutable")
    args.out.mkdir(parents=True)
    history = prepare_history(load_completed_matches())
    market = MarketValueHistory()
    write(args.out / "market_value_audit.json", market.audit())
    policies = ["verified_only", "lagged_season"]
    configs = [("verified_only", "frozen"), ("verified_only", "monthly"), ("lagged_season", "frozen")]
    seasons = ["2021-22", "2022-23", "2023-24", "2025-26"]
    competitions = ["bundesliga", "champions_league"]
    write(args.out / "protocol.json", {
        "development_seasons": seasons[:-1], "heldout_season": seasons[-1],
        "configs": configs, "selection": "Mean development log-loss across the two competitions; verified data only",
        "limitations": ["2025/26 was examined in previous experiments; not an untouched future sample",
                        "Season-only values in lagged sensitivity analysis have no proven availability date",
                        "No historical bookmaker odds: no ROI inferred from these predictions",
                        "Missing CL seasons including 2024/25; raw CL scores not audited for extra time"],
        "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in RAW_PATH.glob("*.csv")},
        "coverage": history.groupby(["competition", "season"]).size().rename("matches").reset_index().to_dict("records"),
    })
    print(f"Building dated features: {len(history)} matches", flush=True)
    features = {policy: build_features(history, policy, market) for policy in policies}
    # Precompute only past-based Poisson once per day; shared by ALL schedules.
    needed = history[history.date >= "2020-01-01"]
    print(f"Computing dated Poisson contexts for {len(needed)} matches", flush=True)
    scores = poisson_for_dates(history, needed)
    pp = np.full((len(history), 3), np.nan)
    keys = ["probability_home_win", "probability_draw", "probability_away_win"]
    for idx, score in scores.items():
        pp[idx] = [score[k] for k in keys]
    log = []
    selected = None
    for season in seasons:
        if season == seasons[-1]:
            dev = pd.DataFrame(log)
            choices = {}
            for strategy, group in dev[dev.policy == "verified_only"].groupby("strategy"):
                choices[strategy] = float(np.mean([
                    probabilities_metrics(g.actual, np.array(g.probabilities.tolist()))["log_loss"]
                    for _, g in group.groupby("competition")
                ]))
            selected = min(choices, key=choices.get)
            write(args.out / "selection.json", {"selected_before_final": selected, "development_scores": choices})
        fixtures = history[(history.season == season) & history.competition.isin(competitions)]
        start = fixtures.date.min()
        for policy, schedule in configs:
            groups = [("season", fixtures)] if schedule == "frozen" else list(fixtures.groupby(fixtures.date.dt.to_period("M")))
            for period, test in groups:
                cutoff = start if schedule == "frozen" else test.date.min()
                print(f"{season} {policy}/{schedule} {period}: fit < {cutoff.date()}, {len(test)} fixtures", flush=True)
                bundle = CalibratedClubModel().fit(history, features[policy], cutoff, pp)
                raw, calibrated = bundle.predict(features[policy].loc[test.index], pp[test.index])
                with (args.out / "predictions.jsonl").open("a") as stream:
                    for treatment, prob in (("raw", raw), ("calibrated", calibrated)):
                        for i, r in enumerate(test.itertuples()):
                            row = {"season": season, "competition": r.competition, "date": str(r.date.date()),
                                   "home": r.home_team, "away": r.away_team, "actual": r.result,
                                   "home_goals": int(r.home_goals), "away_goals": int(r.away_goals),
                                   "policy": policy, "strategy": f"{policy}/{schedule}/{treatment}",
                                   "probabilities": prob[i].tolist(), "fit": bundle.metadata}
                            log.append(row)
                            stream.write(json.dumps(row, allow_nan=False) + "\n")
                write(args.out / "progress.json", {"season": season, "policy": policy, "schedule": schedule, "period": str(period), "predictions": len(log)})
    frame = pd.DataFrame(log)
    results = []
    for (season, competition, strategy), rows in frame.groupby(["season", "competition", "strategy"]):
        results.append({"season": season, "competition": competition, "strategy": strategy,
                        **probabilities_metrics(rows.actual, np.array(rows.probabilities.tolist()))})
    write(args.out / "results.json", {"selected": selected, "results": results})
    lines = ["# Club retraining comparison", "", f"Selected on development: `{selected}`.", "",
             "| Season | Competition | Strategy | n | Accuracy | Log loss | Brier |", "|---|---|---|---:|---:|---:|---:|"]
    for r in results:
        lines.append(f"| {r['season']} | {r['competition']} | {r['strategy']} | {r['n']} | {r['accuracy']:.1%} | {r['log_loss']:.4f} | {r['brier']:.4f} |")
    lines += ["", "No betting profitability claim: historical pre-match odds are absent.",
              "2025/26 has already been used in earlier experiments. Lagged season values are an unverified sensitivity analysis."]
    (args.out / "README.md").write_text("\n".join(lines) + "\n")
    if args.save_model:
        if args.save_model.exists():
            raise SystemExit("Refusing to replace an existing model")
        cutoff = max(pd.Timestamp.now().normalize(), history.date.max() + pd.Timedelta(days=1))
        bundle = CalibratedClubModel().fit(history, features["verified_only"], cutoff, pp)
        from src.club_predictor import ClubFootballPredictor
        predictor = ClubFootballPredictor()
        predictor.use_verified_bundle(history, bundle, calibrated=selected.endswith("/calibrated"))
        predictor.save(args.save_model)
    print(f"Complete: {args.out}", flush=True)


if __name__ == "__main__":
    main()

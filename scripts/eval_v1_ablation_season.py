"""V1 baseline with individual V2 elements toggled on, one at a time, for a
controlled ablation: which piece of V2 (if any) actually helps on a
walk-forward Bundesliga backtest, versus just adopting the whole V2 package?

All V1 characteristics not explicitly toggled stay exactly as in production
V1 (row-by-row feature loop, same POISSON_BLEND=0.30, same recency half-life)
so each flag's effect is isolated against the same baseline used in
scripts/eval_v1_season.py.

    python3 scripts/eval_v1_ablation_season.py --cutoff 2025-08-22 \\
      --fixtures data/season_2025_26_fixtures.json \\
      --out data/season_2025_26_ablation_goalstats_predictions.json \\
      --fix-goal-stats-sort

Flags (any combination): --fix-goal-stats-sort --elo --dated-market-values --catboost
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.feature_engineering import encode_result, _team_form, _h2h_stats, _goal_stats, _decay_weights, FORM_WINDOW
from src.poisson_model import predict_scorelines
from src.models.ensemble_model import EnsemblePredictor
from src.club_predictor import POISSON_BLEND

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "club_football_results.csv"


def _goal_stats_fixed(past, team, prefix):
    home_mask = past["home_team"] == team
    away_mask = past["away_team"] == team
    scored = pd.concat([past.loc[home_mask, "home_goals"], past.loc[away_mask, "away_goals"]]).sort_index().tail(FORM_WINDOW)
    conceded = pd.concat([past.loc[home_mask, "away_goals"], past.loc[away_mask, "home_goals"]]).sort_index().tail(FORM_WINDOW)
    if scored.empty:
        return {f"{prefix}_avg_scored": 0.0, f"{prefix}_avg_conceded": 0.0,
                f"{prefix}_clean_sheets": 0.0, f"{prefix}_avg_goal_diff": 0.0}
    w = _decay_weights(len(scored))
    goal_diff = scored.values - conceded.values
    return {
        f"{prefix}_avg_scored": float(np.dot(scored.values.astype(float), w)),
        f"{prefix}_avg_conceded": float(np.dot(conceded.values.astype(float), w)),
        f"{prefix}_clean_sheets": float(np.dot((conceded.values == 0).astype(float), w)),
        f"{prefix}_avg_goal_diff": float(np.dot(goal_diff.astype(float), w)),
    }


def build_row(past, home, away, args, elo=None):
    goal_stats_fn = _goal_stats_fixed if args.fix_goal_stats_sort else _goal_stats
    features = {}
    features.update(_team_form(past, home, prefix="home"))
    features.update(_team_form(past, away, prefix="away"))
    features.update(_h2h_stats(past, home, away))
    features.update(goal_stats_fn(past, home, prefix="home"))
    features.update(goal_stats_fn(past, away, prefix="away"))

    if args.dated_market_values:
        from src.club_market_values_dated import get_market_value_normalized, get_market_value_ratio
        as_of = past["date"].max() if len(past) else None
        features["home_market_value"] = get_market_value_normalized(home, as_of)
        features["away_market_value"] = get_market_value_normalized(away, as_of)
        features["market_value_ratio"] = get_market_value_ratio(home, away, as_of)
    else:
        from src.club_market_values import get_market_value_normalized, get_market_value_ratio
        features["home_market_value"] = get_market_value_normalized(home)
        features["away_market_value"] = get_market_value_normalized(away)
        features["market_value_ratio"] = get_market_value_ratio(home, away)

    if args.elo:
        features.update(elo.features(home, away))
    return features


def build_features_ablated(df, args):
    df = df.copy().sort_values("date").reset_index(drop=True)
    df["result"] = df.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)
    records = []
    elo = None
    if args.elo:
        from src.club_elo import ClubElo
        elo = ClubElo()
    for idx, row in df.iterrows():
        past = df.iloc[:idx]
        features = {"match_id": idx, "date": row["date"], "home_team": row["home_team"],
                    "away_team": row["away_team"], "result": row["result"]}
        features.update(build_row(past, row["home_team"], row["away_team"], args, elo=elo))
        records.append(features)
        if args.elo:
            # Row-by-row update, matching V1's row-by-row (not day-batched)
            # feature loop above - same same-day-leak characteristic V1
            # already has for form/goal stats, kept consistent on purpose so
            # this flag isolates "adding Elo", not "also fixing same-day
            # batching".
            elo.update_day(df.iloc[[idx]])
    return pd.DataFrame(records).fillna(0)


def build_prediction_row_ablated(df_history, home, away, args, elo=None):
    return pd.DataFrame([build_row(df_history, home, away, args, elo=elo)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fix-goal-stats-sort", action="store_true")
    parser.add_argument("--elo", action="store_true")
    parser.add_argument("--dated-market-values", action="store_true")
    parser.add_argument("--catboost", action="store_true")
    args = parser.parse_args()
    cutoff = pd.Timestamp(args.cutoff)

    print("Ablation flags:", {k: v for k, v in vars(args).items() if k in
          ("fix_goal_stats_sort", "elo", "dated_market_values", "catboost")})

    raw = pd.read_csv(DATA_PATH, parse_dates=["date"])
    raw = raw.rename(columns={"home_score": "home_goals", "away_score": "away_goals"})
    full_history = raw.sort_values("date").reset_index(drop=True)
    full_history["result"] = full_history.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)

    pre_season = full_history[full_history.date < cutoff].reset_index(drop=True)
    print(f"Fitting on {len(pre_season)} matches strictly before {cutoff.date()}")

    features = build_features_ablated(pre_season, args)
    feature_cols = [c for c in features.columns if c not in {"match_id", "date", "home_team", "away_team", "result"}]

    half_life_days = 545
    days_ago = (cutoff - pre_season["date"]).dt.days.clip(lower=0).values
    weights = np.exp(-np.log(2) / half_life_days * days_ago)
    weights = weights / weights.mean()

    model = EnsemblePredictor()
    if args.catboost:
        from src.models.catboost_model import CatBoostPredictor
        model.predictors.append(CatBoostPredictor())
        model.weights = [1 / 3, 1 / 3, 1 / 3]
    model.fit(features[feature_cols], features["result"], sample_weight=weights)

    fixtures = json.loads(args.fixtures.read_text())
    predictions = []
    # Elo needs to be replayed forward for walk-forward inference too - a
    # fresh ClubElo seeded from pre-season, then advanced match-by-match in
    # lockstep with the fixtures loop below (fixtures are already
    # chronological), so predict-time Elo matches what training would have
    # seen at that point without recomputing from scratch every call.
    elo = None
    if args.elo:
        from src.club_elo import ClubElo
        elo = ClubElo()
        for idx, row in pre_season.iterrows():
            elo.update_day(pre_season.iloc[[idx]])

    for i, fx in enumerate(fixtures):
        home, away = fx["home"], fx["away"]
        fx_date = pd.Timestamp(fx["date"])
        history_so_far = full_history[full_history.date < fx_date]

        X = build_prediction_row_ablated(history_so_far, home, away, args, elo=elo)
        for col in feature_cols:
            if col not in X.columns:
                X[col] = 0.0
        X = X[feature_cols]

        clf_proba = model.predict_proba(X)[0]
        poisson_pre = predict_scorelines(history_so_far, home, away)
        poi_proba = [poisson_pre["probability_home_win"], poisson_pre["probability_draw"], poisson_pre["probability_away_win"]]
        blended = [(1 - POISSON_BLEND) * c + POISSON_BLEND * p for c, p in zip(clf_proba, poi_proba)]
        total = sum(blended) or 1.0
        blended = [b / total for b in blended]

        predictions.append({
            "date": fx["date"], "home": home, "away": away,
            "home_goals": fx["home_goals"], "away_goals": fx["away_goals"],
            "probability_home_win": blended[0], "probability_draw": blended[1], "probability_away_win": blended[2],
        })

        if args.elo:
            match_row = full_history[(full_history.date == fx_date) & (full_history.home_team == home) & (full_history.away_team == away)]
            if len(match_row):
                elo.update_day(match_row)

        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(fixtures)}")

    args.out.write_text(json.dumps(predictions, indent=2, ensure_ascii=False))
    print(f"Wrote {len(predictions)} predictions -> {args.out}")


if __name__ == "__main__":
    main()

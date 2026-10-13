"""Step 4 of docs/form_xg_plan.md: the Elo mix inside the real club model.

    python3 scripts/eval_elo_mix_club.py

The production club model (src/club_backtest.CalibratedClubModel: RF, XGBoost
and CatBoost on src/club_features_v3, blended 70/30 with the Poisson model,
temperature-calibrated) uses no Elo at all. So three feature sets, the rest
of the recipe unchanged:

  v3          production features
  v3 + Elo    plus Elo from results (src/club_elo.ClubElo: K 20, home 60)
  v3 + mix    plus Elo updated 70 % from the xG result where a Bundesliga
              match has xG (scripts/form_xg_rolling.py), from the result
              everywhere else (Champions League, 2. Bundesliga, older seasons)

Each season is predicted by a model frozen at its start, as in production
(scripts/validate_club_retraining.py): 2021-22, 2022-23, 2023-24, 2024-25
(no Champions League data) and 2025-26. Reported per competition, with a
paired bootstrap interval of the log-loss difference to v3.

The 70 % share was picked in the season-by-season test, partly on seasons
that are tested here; a small optimism for the mix is possible.

Writes data/model_reports/elo_mix_club_20261010.json.

    python3 scripts/eval_elo_mix_club.py --confirm

The confirmation check, declared before it was run: the Champions League
seasons 2014-15, 2015-16 and 2016-17, untouched by the run above. Confirmed
if v3 + Elo beats v3 there with the 95 % interval entirely below 0. Writes
data/model_reports/elo_club_confirm_20261010.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.club_backtest import CalibratedClubModel, poisson_for_dates, probabilities_metrics  # noqa: E402
from src.club_data_loader import load_completed_matches  # noqa: E402
from src.club_features_v3 import build_features, prepare_history  # noqa: E402

OUT = ROOT / "data" / "model_reports" / "elo_mix_club_20261010.json"
SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
COMPETITIONS = ["bundesliga", "champions_league"]
K, HOME, INITIAL, MIX = 20.0, 60.0, 1500.0, 0.7


def load_xg():
    xg = {}
    for path in sorted((ROOT / "data" / "club_stats").glob("bundesliga_*.csv")):
        for r in csv.DictReader(path.open(encoding="utf-8")):
            if r["home_xg"] and r["away_xg"]:
                xg[(r["date"], r["home_team"], r["away_team"])] = (float(r["home_xg"]), float(r["away_xg"]))
    return xg


def xg_result(lh, la, n=10):
    ph = [math.exp(-lh) * lh ** i / math.factorial(i) for i in range(n)]
    pa = [math.exp(-la) * la ** i / math.factorial(i) for i in range(n)]
    return sum(ph[i] * pa[j] for i in range(n) for j in range(i)) + 0.5 * sum(ph[i] * pa[i] for i in range(n))


def elo_features(history, xg, mix):
    """Elo before each match, date batches like src/club_elo.ClubElo."""
    ratings, rows = {}, {}
    for date, day in history.groupby("date", sort=True):
        for r in day.itertuples():
            h, a = ratings.get(r.home_team, INITIAL), ratings.get(r.away_team, INITIAL)
            rows[r.Index] = {"elo_diff": h - a, "elo_expected_score": 1 / (1 + 10 ** ((a - h - HOME) / 400))}
        changes = defaultdict(float)
        for r in day.itertuples():
            expected = rows[r.Index]["elo_expected_score"]
            actual = 1.0 if r.home_goals > r.away_goals else 0.0 if r.home_goals < r.away_goals else 0.5
            chances = xg.get((str(date.date()), r.home_team, r.away_team)) if mix else None
            if chances:
                actual = (1 - mix) * actual + mix * xg_result(*chances)
            changes[r.home_team] += K * (actual - expected)
            changes[r.away_team] -= K * (actual - expected)
        for team, d in changes.items():
            ratings[team] = ratings.get(team, INITIAL) + d
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="the Champions League confirmation check")
    args = parser.parse_args()
    global SEASONS, COMPETITIONS, OUT
    since = "2020-01-01"
    if args.confirm:
        SEASONS, COMPETITIONS, since = ["2014-15", "2015-16", "2016-17"], ["champions_league"], "2013-06-01"
        OUT = ROOT / "data" / "model_reports" / "elo_club_confirm_20261010.json"
    history = prepare_history(load_completed_matches())
    xg = load_xg()
    v3 = build_features(history)
    variants = {"v3": v3,
                "v3 + Elo": pd.concat([v3, elo_features(history, xg, 0.0)], axis=1),
                "v3 + Elo-Mischung": pd.concat([v3, elo_features(history, xg, MIX)], axis=1)}
    used = sum((str(d.date()), h, a) in xg for d, h, a in zip(history.date, history.home_team, history.away_team))
    print(f"{len(history)} matches, {used} with xG in the mix", flush=True)
    needed = history[history.date >= since]
    print(f"Poisson for {len(needed)} matches...", flush=True)
    scores = poisson_for_dates(history, needed)
    pp = np.full((len(history), 3), np.nan)
    for idx, s in scores.items():
        pp[idx] = [s[k] for k in ("probability_home_win", "probability_draw", "probability_away_win")]

    log = []
    for season in SEASONS:
        test = history[(history.season == season) & history.competition.isin(COMPETITIONS)]
        cutoff = test.date.min()
        for name, X in variants.items():
            bundle = CalibratedClubModel().fit(history, X, cutoff, pp)
            _, p = bundle.predict(X.loc[test.index], pp[test.index])
            for i, r in enumerate(test.itertuples()):
                log.append({"season": season, "competition": r.competition, "variant": name, "idx": int(r.Index),
                            "actual": r.result, "p": p[i].tolist()})
            m = probabilities_metrics(test.result, p)
            print(f"{season} {name:18s} n={m['n']:3d}  log-loss {m['log_loss']:.4f}  acc {m['accuracy']:.3f}", flush=True)

    frame = pd.DataFrame(log)
    report = {"seasons": SEASONS, "mix": MIX, "results": []}
    rng = np.random.default_rng(0)
    print()
    for comp in COMPETITIONS + ["alle"]:
        sub = frame if comp == "alle" else frame[frame.competition == comp]
        piv = {v: g.sort_values(["season", "idx"]) for v, g in sub.groupby("variant")}
        y = piv["v3"].actual.map({"H": 0, "D": 1, "A": 2}).to_numpy()
        ll = {v: -np.log(np.array(g.p.tolist())[np.arange(len(y)), y].clip(1e-12)) for v, g in piv.items()}
        idx = [rng.integers(0, len(y), len(y)) for _ in range(2000)]
        for v in ("v3", "v3 + Elo", "v3 + Elo-Mischung"):
            d = ll[v] - ll["v3"]
            ci = np.percentile([d[i].mean() for i in idx], [2.5, 97.5])
            row = {"competition": comp, "variant": v, "n": int(len(y)), "log_loss": round(float(ll[v].mean()), 4),
                   "diff_vs_v3": round(float(d.mean()), 4), "ci": [round(float(c), 4) for c in ci]}
            if v == "v3 + Elo-Mischung":
                e = ll[v] - ll["v3 + Elo"]
                ce = np.percentile([e[i].mean() for i in idx], [2.5, 97.5])
                row["diff_vs_elo"] = round(float(e.mean()), 4)
                row["ci_vs_elo"] = [round(float(c), 4) for c in ce]
            report["results"].append(row)
            extra = (f"  | vs Elo {row['diff_vs_elo']:+.4f} [{row['ci_vs_elo'][0]:+.4f}, {row['ci_vs_elo'][1]:+.4f}]"
                     if "diff_vs_elo" in row else "")
            print(f"{comp:16s} {v:18s} n={len(y):4d}  log-loss {row['log_loss']:.4f}  "
                  f"Δ vs v3 {row['diff_vs_v3']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]{extra}")
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(f"\ngeschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

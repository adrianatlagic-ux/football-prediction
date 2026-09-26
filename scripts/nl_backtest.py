"""The national model against the betting market, Nations League 2020-21 and 2024-25.

    python3 scripts/nl_backtest.py

The model the site runs was trained on every international up to June 2026,
those Nations League seasons included, so asking it about them now would
be asking a question it has seen the answer to. For each season a model is
trained here on matches before the season only (the same procedure as
FootballPredictor.train), and each match is then predicted with the history
up to the day before it - as the site would have predicted it then.

The market is the average of the bookmakers OddsPortal lists (German
licences; Pinnacle is not among them), margin removed.

One advantage remains with the model and cannot be taken away: its FIFA
ranking and squad value features are today's, not the season's. The model
knows how strong a team turned out to be. If it still does not beat the
market, that only strengthens the result.

Writes data/model_reports/nl_backtest_20260927/cases.jsonl (one row per
match and outcome) and summary.json; scripts/build_model_track_record.py
reads the cases as the Nations League archive.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ODDS = ROOT / "data" / "odds_archive" / "oddsportal_nl_20260927"
OUT = ROOT / "data" / "model_reports" / "nl_backtest_20260927"
SEASONS = {"2020-2021": "2020-09-01", "2024-2025": "2024-09-01"}
# OddsPortal and the results file spell some nations differently.
NAMES = {"Bosnia & Herzegovina": "Bosnia and Herzegovina", "Czechia": "Czech Republic",
         "Turkiye": "Turkey", "Türkiye": "Turkey", "Macedonia": "North Macedonia",
         "Ireland": "Republic of Ireland", "Faroe Islands": "Faroe Islands"}


def name(n: str) -> str:
    return NAMES.get(n, n)


def odds_rows(season: str) -> list:
    rows = []
    for m in json.load((ODDS / f"nl_{season}.json").open()):
        o = m.get("odds") or {}
        try:
            avg = [float(o[k]["average"]) for k in ("home", "draw", "away")]
            hs, as_ = (int(x) for x in str(m["result"]).split(":")[:2])
        except (KeyError, TypeError, ValueError):
            continue
        inv = [1 / p for p in avg]
        rows.append({"date": m["startTime"][:10], "home": name(m["homeTeam"]), "away": name(m["awayTeam"]),
                     "market": [x / sum(inv) for x in inv], "books": o["home"].get("bookmakerCount"),
                     "result": 0 if hs > as_ else 1 if hs == as_ else 2})
    return rows


def train_until(cutoff: str):
    """A national model trained on matches before `cutoff` only."""
    import src.predictor as predictor_module
    from src.data_loader import load_completed_matches
    everything = load_completed_matches()
    before = everything[everything["date"] < pd.Timestamp(cutoff)].reset_index(drop=True)
    original = predictor_module.load_completed_matches
    predictor_module.load_completed_matches = lambda: before.copy()
    try:
        model = predictor_module.FootballPredictor()
        model.train(since_year=1990)
    finally:
        predictor_module.load_completed_matches = original
    return model, everything


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases, summary = [], {}
    for season, cutoff in SEASONS.items():
        print(f"{season}: Modell bis {cutoff} trainieren ...", flush=True)
        model, everything = train_until(cutoff)
        from src.feature_engineering import encode_result
        everything = everything[everything["date"].dt.year >= 1990].copy()
        everything["result"] = [encode_result(h, a) for h, a in zip(everything["home_goals"], everything["away_goals"])]
        rows = odds_rows(season)
        n = ll_model = ll_market = 0.0
        skipped = 0
        for r in rows:
            # History up to the day before the match, as the site would have had it.
            model._history = everything[everything["date"] < pd.Timestamp(r["date"])].reset_index(drop=True)
            try:
                p = model.predict_match(r["home"], r["away"], is_knockout=False)
            except Exception:
                skipped += 1
                continue
            mp = [p["probability_home_win"], p["probability_draw"], p["probability_away_win"]]
            total = sum(mp)
            mp = [x / total for x in mp]
            n += 1
            ll_model += -np.log(max(mp[r["result"]], 1e-12))
            ll_market += -np.log(max(r["market"][r["result"]], 1e-12))
            for i in range(3):
                cases.append({"season": season, "date": r["date"], "home": r["home"], "away": r["away"],
                              "outcome": i, "model": mp[i], "market": r["market"][i],
                              "won": r["result"] == i, "books": r["books"]})
        summary[season] = {"matches": int(n), "skipped": skipped, "cutoff": cutoff,
                           "logloss_model": ll_model / n if n else None,
                           "logloss_market": ll_market / n if n else None}
        print(f"  {int(n)} Spiele (uebersprungen {skipped})  Log-Loss Modell {ll_model / n:.4f}  "
              f"Markt {ll_market / n:.4f}", flush=True)
    with (OUT / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(f"geschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

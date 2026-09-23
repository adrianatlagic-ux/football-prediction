"""Is the second division a softer market than the first?

Betting edges, where they exist at all, tend to sit in competitions that
attract less professional money. We have 4590 second-division matches in
training - almost as many as first-division - but every profitability test so
far used the Bundesliga only, because the stored predictions covered nothing
else.

This runs the same chronological recipe on 2. Bundesliga fixtures, joins
football-data's Bet365/best prices, and applies the same selection the live
system uses: back the highest-Kelly candidate with a positive edge. Results
are directly comparable to the first-division numbers.

    python3 scripts/evaluate_bundesliga2.py

Prices are the best available across bookmakers, matching what the live
pipeline takes. Closing prices give the same closing-line check as the
first-division run.
"""
import argparse
import csv
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

ODDS_DIR = ROOT / "data" / "odds_archive" / "football_data_d2_20260923"
SEASONS = ["2021-22", "2022-23", "2023-24", "2025-26"]
POLICY = "verified_only"
OUTCOMES = ["home_win", "draw", "away_win"]
COLS = {"home_win": ("MaxH", "MaxCH"), "draw": ("MaxD", "MaxCD"), "away_win": ("MaxA", "MaxCA")}

# football-data's second-division spellings -> ours.
ALIASES = {
    "Braunschweig": "Eintracht Braunschweig", "Dresden": "Dynamo Dresden",
    "Erzgebirge Aue": "FC Erzgebirge Aue", "Fortuna Dusseldorf": "Fortuna Düsseldorf",
    "Hannover": "Hannover 96", "Ingolstadt": "FC Ingolstadt 04",
    "Kaiserslautern": "1. FC Kaiserslautern", "Karlsruhe": "Karlsruher SC",
    "Magdeburg": "1. FC Magdeburg", "Nurnberg": "1. FC Nürnberg",
    "Osnabruck": "VfL Osnabrück", "Paderborn": "SC Paderborn",
    "Regensburg": "Jahn Regensburg", "Sandhausen": "SV Sandhausen",
    "Wehen": "SV Wehen Wiesbaden", "Bielefeld": "Arminia Bielefeld",
    "Bochum": "VfL Bochum", "Darmstadt": "SV Darmstadt 98",
    "Greuther Furth": "Greuther Fürth", "Hamburg": "Hamburger SV",
    "Hansa Rostock": "Hansa Rostock", "Heidenheim": "1. FC Heidenheim",
    "Hertha": "Hertha Berlin", "Holstein Kiel": "Holstein Kiel",
    "Koln": "1. FC Köln", "FC Koln": "1. FC Köln", "St Pauli": "FC St. Pauli",
    "Schalke 04": "Schalke 04", "Elversberg": "Elversberg", "Munster": "Preußen Münster",
    "Ulm": "SSV Ulm 1846", "Cottbus": "FC Energie Cottbus",
}


def load_odds():
    table = {}
    for path in sorted(ODDS_DIR.glob("D2_*.csv")):
        for row in csv.DictReader(path.open(encoding="utf-8-sig", errors="ignore")):
            date = (row.get("Date") or "").strip()
            if not date:
                continue
            d, m, y = date.split("/")
            y = y if len(y) == 4 else "20" + y
            home = ALIASES.get((row.get("HomeTeam") or "").strip(), (row.get("HomeTeam") or "").strip())
            away = ALIASES.get((row.get("AwayTeam") or "").strip(), (row.get("AwayTeam") or "").strip())
            prices = {}
            for outcome, (pre, close) in COLS.items():
                try:
                    a, b = float(row[pre]), float(row[close])
                except (KeyError, TypeError, ValueError):
                    continue
                if a > 1 and b > 1:
                    prices[outcome] = (a, b)
            if len(prices) == 3:
                table[(f"{y}-{m}-{d}", home, away)] = prices
    return table


def devig(prices):
    implied = [1 / p for p in prices]
    return [v / sum(implied) for v in implied]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "data/model_reports/bundesliga2_20260923.json")
    args = ap.parse_args()

    odds = load_odds()
    print(f"{len(odds)} Zweitliga-Spiele mit Quoten")

    history = prepare_history(load_completed_matches())
    market = MarketValueHistory()
    print("Baue Features...", flush=True)
    X = build_features(history, POLICY, market)
    needed = history[history.date >= "2020-01-01"]
    print(f"Poisson-Kontexte fuer {len(needed)} Spiele...", flush=True)
    scores = poisson_for_dates(history, needed)
    pp = np.full((len(history), 3), np.nan)
    keys = ["probability_home_win", "probability_draw", "probability_away_win"]
    for idx, s in scores.items():
        pp[idx] = [s[k] for k in keys]

    bets, unmatched = [], 0
    for season in SEASONS:
        fixtures = history[(history.season == season) & (history.competition == "bundesliga2")]
        if fixtures.empty:
            continue
        cutoff = fixtures.date.min()
        print(f"{season}: fit < {cutoff.date()}, {len(fixtures)} Spiele", flush=True)
        bundle = CalibratedClubModel().fit(history, X, cutoff, pp)
        raw, _ = bundle.predict(X.loc[fixtures.index, bundle.feature_columns], pp[fixtures.index])

        for i, r in enumerate(fixtures.itertuples()):
            key = (str(r.date.date()), r.home_team, r.away_team)
            if key not in odds:
                unmatched += 1
                continue
            pre_probs = devig([odds[key][o][0] for o in OUTCOMES])
            cands = []
            for j, outcome in enumerate(OUTCOMES):
                taken, closing = odds[key][outcome]
                p = float(raw[i][j])
                ev = p * taken - 1
                kelly = max(0.0, ev / (taken - 1)) / 4
                cands.append({"outcome": outcome, "p": p, "q": pre_probs[j], "taken": taken,
                              "closing": closing, "ev": ev, "kelly": kelly,
                              # Same guard the live selector applies.
                              "suspicious": ev > 0.25 or abs(p - pre_probs[j]) > 0.15})
            clean = [c for c in cands if c["ev"] > 0 and not c["suspicious"]]
            if not clean:
                continue
            pick = max(clean, key=lambda c: c["kelly"])
            won = ((pick["outcome"] == "home_win" and r.home_goals > r.away_goals)
                   or (pick["outcome"] == "draw" and r.home_goals == r.away_goals)
                   or (pick["outcome"] == "away_win" and r.away_goals > r.home_goals))
            bets.append({"season": season, "date": str(r.date.date()),
                         "home": r.home_team, "away": r.away_team, **pick,
                         "profit": pick["taken"] - 1 if won else -1.0,
                         "clv": pick["taken"] / pick["closing"] - 1})

    if not bets:
        raise SystemExit("Keine Wetten zuordenbar.")
    profit = np.array([b["profit"] for b in bets])
    clv = np.array([b["clv"] for b in bets])
    rng = np.random.default_rng(0)
    roi_ci = np.percentile(profit[rng.integers(0, len(profit), (8000, len(profit)))].mean(1), [2.5, 97.5])
    clv_ci = np.percentile(clv[rng.integers(0, len(clv), (8000, len(clv)))].mean(1), [2.5, 97.5])

    print(f"\nnicht zuordenbar: {unmatched}")
    print(f"\n  Wetten              {len(bets)}")
    print(f"  Treffer             {(profit > 0).mean():.1%}")
    print(f"  ROI                 {profit.mean():+.2%}   95% [{roi_ci[0]:+.1%}, {roi_ci[1]:+.1%}]")
    print(f"  CLV                 {clv.mean():+.2%}   95% [{clv_ci[0]:+.2%}, {clv_ci[1]:+.2%}]")
    print(f"  besser als Schluss  {(clv > 0).mean():.1%}")

    print(f"\n  {'Saison':10} {'Wetten':>7} {'ROI':>9} {'CLV':>9}")
    for season in SEASONS:
        s = [b for b in bets if b["season"] == season]
        if not s:
            continue
        p = np.array([b["profit"] for b in s])
        c = np.array([b["clv"] for b in s])
        print(f"  {season:10} {len(s):7d} {p.mean():+8.1%} {c.mean():+8.2%}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "competition": "bundesliga2", "bets": len(bets), "unmatched": unmatched,
        "roi": float(profit.mean()), "roi_ci95": [float(v) for v in roi_ci],
        "hit_rate": float((profit > 0).mean()),
        "clv": float(clv.mean()), "clv_ci95": [float(v) for v in clv_ci],
        "share_beating_close": float((clv > 0).mean()),
        "by_season": {s: {"bets": len([b for b in bets if b["season"] == s]),
                          "roi": float(np.mean([b["profit"] for b in bets if b["season"] == s])),
                          "clv": float(np.mean([b["clv"] for b in bets if b["season"] == s]))}
                      for s in SEASONS if any(b["season"] == s for b in bets)},
        "limits": ["Retrospective; season-frozen fits, not archived live tips",
                   "1X2 only; best available price across books",
                   "Same positive-edge Kelly selection as the live system"],
    }, indent=2) + "\n")
    print(f"\ngeschrieben: {args.out}")


if __name__ == "__main__":
    main()

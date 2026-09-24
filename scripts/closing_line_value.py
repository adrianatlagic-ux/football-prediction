"""Do our picks beat the closing line?

ROI is a noisy way to ask whether a betting model has an edge: the intervals
in the selection comparison run from -82% to +18%, which decides nothing.
Closing line value asks the sharper question. The closing price is the
market's best estimate, because everything known about the match is in it by
then. A bettor who repeatedly takes prices better than the eventual close is
finding real information; one who takes worse prices is behind the market,
whatever individual bets happen to do.

The measure needs far fewer samples than ROI because it compares two prices
directly instead of waiting for outcomes to average out.

    python3 scripts/closing_line_value.py

Read it as follows. Clearly negative means the model trails the market and
the losses are structural, not bad luck. Around zero means no edge either
way, and the losses are the bookmaker's margin. Clearly positive alongside
negative ROI would be a contradiction worth chasing.

Data: the same football-data Bet365 archive as the selection comparison,
which carries an opening and a closing price per match. Bundesliga only, one
bookmaker, retrospective.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ODDS_DIR = ROOT / "data" / "odds_archive" / "football_data_20260923"
DECISIONS = ROOT / "data" / "model_reports" / "selection_comparison_20260923" / "decisions.jsonl"

# football-data column pairs: pre-closing (B365*) and closing (B365C*).
COLS = {"home_win": ("B365H", "B365CH"), "draw": ("B365D", "B365CD"), "away_win": ("B365A", "B365CA")}


def load_odds():
    """date+teams -> {outcome: (pre, close)} using football-data's own names."""
    from scripts.compare_bet_selection import ALIASES
    table = {}
    for path in sorted(ODDS_DIR.glob("*.csv")):
        with path.open(encoding="utf-8-sig", errors="ignore") as fh:
            for row in csv.DictReader(fh):
                date = (row.get("Date") or "").strip()
                if not date:
                    continue
                d, m, y = date.split("/")
                y = y if len(y) == 4 else ("20" + y)
                home = ALIASES.get((row.get("HomeTeam") or "").strip(), (row.get("HomeTeam") or "").strip())
                away = ALIASES.get((row.get("AwayTeam") or "").strip(), (row.get("AwayTeam") or "").strip())
                prices = {}
                for outcome, (pre_col, close_col) in COLS.items():
                    try:
                        pre, close = float(row[pre_col]), float(row[close_col])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if pre > 1 and close > 1:
                        prices[outcome] = (pre, close)
                if len(prices) == 3:
                    table[(f"{y}-{m}-{d}", home, away)] = prices
    return table


def devig(prices, index):
    """Margin-free probability for one outcome from a complete 1X2 set."""
    implied = [1 / p for p in prices]
    return implied[index] / sum(implied)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "data/model_reports/clv_20260923.json")
    args = ap.parse_args()

    odds = load_odds()
    rows = [json.loads(l) for l in DECISIONS.open() if l.strip()]
    rows = [r for r in rows if r["scope"] == "1x2_preclosing"]
    print(f"{len(odds)} Spiele mit Eroeffnungs- und Schlussquote, {len(rows)} Entscheidungszeilen")

    outcomes = ["home_win", "draw", "away_win"]
    records, missing = [], 0
    for r in rows:
        pick = r["decisions"].get("kelly_baseline")
        if not pick:
            continue
        key = (r["date"], r["home"], r["away"])
        if key not in odds:
            missing += 1
            continue
        outcome = pick["outcome"]
        if outcome not in COLS:
            continue
        pre, close = odds[key][outcome]
        i = outcomes.index(outcome)
        records.append({
            "date": r["date"], "season": r["season"],
            "home": r["home"], "away": r["away"], "outcome": outcome,
            "taken": pre, "closing": close,
            # Positive = we took a better price than the market settled on.
            "clv_pct": pre / close - 1,
            "prob_taken": devig([odds[key][o][0] for o in outcomes], i),
            "prob_closing": devig([odds[key][o][1] for o in outcomes], i),
            "model_prob": pick["probability"],
        })

    if not records:
        raise SystemExit("Keine zuordenbaren Wetten.")
    clv = np.array([x["clv_pct"] for x in records])
    beat = float((clv > 0).mean())
    rng = np.random.default_rng(0)
    sims = clv[rng.integers(0, len(clv), (4000, len(clv)))].mean(1)
    ci = [float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))]

    print(f"\nnicht zuordenbar: {missing}")
    print(f"ausgewertete Wetten: {len(records)}")
    print(f"\n  mittlerer CLV        {clv.mean():+.2%}")
    print(f"  95%-Intervall        {ci[0]:+.2%} bis {ci[1]:+.2%}")
    print(f"  Anteil besser als Schlussquote  {beat:.1%}   (ohne Vorteil ~50%)")

    print(f"\n  {'Saison':10} {'Wetten':>7} {'CLV':>9} {'> Schluss':>11}")
    per = defaultdict(list)
    for x in records:
        per[x["season"]].append(x["clv_pct"])
    for season, vals in sorted(per.items()):
        v = np.array(vals)
        print(f"  {season:10} {len(v):7d} {v.mean():+8.2%} {(v > 0).mean():10.1%}")

    # A model with information should be further from the closing estimate in
    # the right direction, not just differently priced.
    model_edge = np.array([x["model_prob"] - x["prob_closing"] for x in records])
    print(f"\n  Modell minus Schlussmarkt (Wahrscheinlichkeit): {model_edge.mean():+.3f}")
    print(f"  Anteil, bei dem das Modell ueber dem Schlussmarkt lag: {(model_edge > 0).mean():.1%}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "bets": len(records), "unmatched": missing,
        "mean_clv": float(clv.mean()), "clv_ci95": ci,
        "share_beating_close": beat,
        "by_season": {s: {"bets": len(v), "mean_clv": float(np.mean(v)),
                          "share_beating_close": float((np.array(v) > 0).mean())}
                      for s, v in per.items()},
        "mean_model_minus_closing_probability": float(model_edge.mean()),
        "limits": ["Bundesliga only, single bookmaker (Bet365)",
                   "Retrospective; not archived live tips",
                   "1X2 only - football-data carries no closing handicap or totals",
                   "Opening price used as the taken price; our real timing differed"],
    }, indent=2) + "\n")
    print(f"\ngeschrieben: {args.out}")


if __name__ == "__main__":
    main()

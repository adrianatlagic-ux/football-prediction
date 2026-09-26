"""Does the model beat the market where the market is thin?

    python3 scripts/thin_market_test.py

Across all Bundesliga matches the model adds nothing to Pinnacle's price
(scripts/does_the_model_add_anything.py). The idea tested here: a market is
sharpest where most money goes and weakest where little does, so the model
might know something the price missed on the quiet matches - and should be
allowed a say there only.

Three measures of a quiet market, each split into thirds on the development
seasons (2021-22, 2022-23) and judged on 2023-24 and 2025-26:

  margin     Pinnacle's overround before the close - books widen it where
             they know less
  spread     how far the best price stands above the average (Max/Avg) -
             bookmakers disagreeing about the match
  size       the smaller club's squad value that season - small clubs draw
             less betting

In each third the model is blended into Pinnacle's pre-closing price (the
price when a bet is placed) with the weight that did best on the
development seasons; the holdout says whether it helps. Only a holdout
improvement whose 95% interval stays above zero counts.

Only the Bundesliga has both an odds archive and point-in-time model
predictions; the thinnest markets of all (small nations, Champions League
outsiders) have no odds archive to test on.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_bet_selection import ALIASES  # noqa: E402
from scripts.does_the_model_add_anything import DECISIONS, DEV, FD, HOLD, IDX, fair  # noqa: E402

OUT = ROOT / "data" / "model_reports" / "thin_market_20260926.json"


def season_of(date: str) -> str:
    y, m = int(date[:4]), int(date[5:7])
    start = y if m >= 7 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def club_values() -> dict:
    from scripts.build_club_training_data import _canon
    out = {}
    with (ROOT / "data" / "club_market_values_history.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                out[(int(r["season_start_year"]), _canon(r["team"]))] = float(r["market_value"])
            except (KeyError, ValueError):
                continue
    return out


def load() -> list:
    from scripts.build_club_training_data import _canon
    values = club_values()
    archive = {}
    for path in sorted(FD.glob("D1_*.csv")):
        for r in csv.DictReader(path.open(encoding="utf-8-sig", errors="ignore")):
            try:
                pre = [float(r[k]) for k in ("PSH", "PSD", "PSA")]
                close = [float(r[k]) for k in ("PSCH", "PSCD", "PSCA")]
                mx = [float(r[k]) for k in ("MaxH", "MaxD", "MaxA")]
                avg = [float(r[k]) for k in ("AvgH", "AvgD", "AvgA")]
            except (KeyError, ValueError):
                continue
            d, m, y = r["Date"].split("/")
            y = y if len(y) == 4 else "20" + y
            date = f"{y}-{m}-{d}"
            home = ALIASES.get(r["HomeTeam"].strip(), r["HomeTeam"].strip())
            away = ALIASES.get(r["AwayTeam"].strip(), r["AwayTeam"].strip())
            start = int(season_of(date)[:4])
            v = [values.get((start, _canon(home))), values.get((start, _canon(away)))]
            archive[(date, home, away)] = {
                "pre": fair(pre), "close": fair(close), "result": {"H": 0, "D": 1, "A": 2}[r["FTR"]],
                "margin": sum(1 / p for p in pre) - 1,
                "spread": max(x / a - 1 for x, a in zip(mx, avg)),
                "size": min(v) if None not in v else None,
            }
    rows = []
    for row in (json.loads(line) for line in DECISIONS.open()):
        if row["scope"] != "1x2_preclosing":
            continue
        a = archive.get((row["date"], row["home"], row["away"]))
        if not a:
            continue
        model = [None] * 3
        for c in row["candidates"]:
            if c["outcome"] in IDX:
                model[IDX[c["outcome"]]] = float(c["probability"])
        if None in model:
            continue
        total = sum(model)
        rows.append({**a, "season": row["season"], "model": [x / total for x in model]})
    return rows


def losses(rows, w, key="pre"):
    return np.array([-np.log(max((1 - w) * r[key][r["result"]] + w * r["model"][r["result"]], 1e-12))
                     for r in rows])


def evaluate_segment(dev, hold, rng):
    grid = np.round(np.arange(0, 1.0001, 0.05), 2)
    best = min((losses(dev, w).mean(), w) for w in grid)[1]
    diff = losses(hold, best) - losses(hold, 0.0)
    ci = np.percentile(diff[rng.integers(0, len(diff), (4000, len(diff)))].mean(1), [2.5, 97.5])
    return {"n_dev": len(dev), "n_hold": len(hold), "best_weight": float(best),
            "pinnacle_logloss": float(losses(hold, 0.0).mean()),
            "model_logloss": float(losses(hold, 1.0).mean()),
            "improvement": float(-diff.mean()), "ci95": [float(-ci[1]), float(-ci[0])],
            "helps": bool(ci[1] < 0)}


def main():
    rows = load()
    dev = [r for r in rows if r["season"] in DEV]
    hold = [r for r in rows if r["season"] in HOLD]
    rng = np.random.default_rng(0)
    print(f"{len(dev)} Entwicklungs-, {len(hold)} Pruefspiele (Bundesliga)\n")
    report = {"all": evaluate_segment(dev, hold, rng)}
    a = report["all"]
    print(f"  alle Spiele            Beimischung {a['best_weight']:.0%}  Verbesserung {a['improvement']:+.4f} "
          f"[{a['ci95'][0]:+.4f}, {a['ci95'][1]:+.4f}]\n")
    for feature, label, quiet_is_high in (("margin", "Pinnacle-Marge", True),
                                          ("spread", "Uneinigkeit der Buchmacher", True),
                                          ("size", "Kaderwert des kleineren Teams", False)):
        # Thirds within each season: Pinnacle's margin and the spread of
        # prices drift from season to season, and cut-offs from the early
        # seasons put almost every later match into one third.
        for rs in (dev, hold):
            for season in {r["season"] for r in rs}:
                vals = [r[feature] for r in rs if r["season"] == season and r[feature] is not None]
                if not vals:
                    continue
                cuts = np.percentile(vals, [100 / 3, 200 / 3])
                for r in rs:
                    if r["season"] == season and r[feature] is not None:
                        r[f"{feature}_third"] = int(r[feature] > cuts[0]) + int(r[feature] > cuts[1])
        d = [r for r in dev if f"{feature}_third" in r]
        h = [r for r in hold if f"{feature}_third" in r]
        print(f"  {label} (Drittel je Saison)")
        report[feature] = {}
        for i, name in enumerate(("unteres Drittel", "mittleres Drittel", "oberes Drittel")):
            def part(rs):
                return [r for r in rs if r[f"{feature}_third"] == i]
            res = evaluate_segment(part(d), part(h), rng)
            quiet = (i == 2) == quiet_is_high
            report[feature][name] = {**res, "quietest": quiet and i in (0, 2)}
            mark = "  <- ruhigster Markt" if (quiet and i in (0, 2)) else ""
            print(f"    {name:18} n={res['n_hold']:3}  Beimischung {res['best_weight']:.0%}  "
                  f"Pinnacle {res['pinnacle_logloss']:.4f}  Modell {res['model_logloss']:.4f}  "
                  f"Verbesserung {res['improvement']:+.4f} [{res['ci95'][0]:+.4f}, {res['ci95'][1]:+.4f}]"
                  f"  {'HILFT' if res['helps'] else 'kein Nutzen'}{mark}")
        print()
    OUT.write_text(json.dumps(report, indent=1) + "\n")
    print(f"geschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

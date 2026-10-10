"""Second, larger test of chance-quality features: season by season.

    python3 scripts/form_xg_rolling.py

Follows scripts/form_xg_probe.py, whose 1,260 test matches could not tell
apart effects of 0.003 log-loss from chance. Declared before running it:

  candidates  Elo mix (Elo from result and xG result) and the shot rating;
              the xG rating and the xG average are reported for information
  design      for each test season F from 2018-19 on: settings (rating speed
              and season pull, or the mix share) chosen by fitting on
              2015-16..F-2 and judging on F-1; then fitted on 2015-16..F-1
              and tested on F. All test seasons pooled, about 2,500 matches.
  success     the 95 % bootstrap interval of the pooled log-loss difference
              to the base lies entirely below 0, and the same variant was
              already ahead in the first test

Features are chronological in every pass (built once per setting), so
choosing a setting per season uses nothing from that season.

Writes data/model_reports/form_xg_rolling_20261010.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import log_loss

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import form_xg_probe as probe  # noqa: E402

OUT = ROOT / "data" / "model_reports" / "form_xg_rolling_20261010.json"
FIRST_TEST = 2018
FIRST_FIT = 2015


def main():
    settings = [(k, pull) for k in probe.K_GRID for pull in probe.PULL_GRID]
    builds = {}
    for i, (k, pull) in enumerate(settings, 1):
        builds[(k, pull)] = probe.build(k, pull, k, pull)
        print(f"  features {i}/{len(settings)}", end="\r")
    X0 = builds[settings[0]]
    last = int(X0.start.max())
    base_cols = probe.BASE
    mix_cols = lambda w: [f"elo_mix{int(w * 100)}", "log_mv_ratio", "mv_missing"]

    def choose(kind_cols, fit_rows, val_rows):
        """The setting (or mix share) with the lowest validation log-loss."""
        scores = {}
        for key, cols in kind_cols.items():
            X = builds[key[0]]
            fit, val = X[fit_rows(X)], X[val_rows(X)]
            scores[key] = log_loss(val.y, probe.fit_predict(fit, val, cols), labels=[0, 1, 2])
        return min(scores, key=scores.get)

    candidates = {
        "Elo-Mischung": lambda: {((settings[0]), w): mix_cols(w) for w in probe.MIX_GRID},
        "Schuss-Bewertung": lambda: {(s, None): base_cols + probe.RATING("sot") for s in settings},
        "xG-Bewertung (Info)": lambda: {(s, None): base_cols + probe.RATING("xg") for s in settings},
        "xG-Durchschnitt (Info)": lambda: {((settings[0]), None): base_cols + probe.both(["xgf", "xga"])},
    }
    losses = {name: [] for name in ["Basis", *candidates]}
    per_season, chosen = [], {name: {} for name in candidates}
    ys = []
    for F in range(FIRST_TEST, last + 1):
        test_rows = lambda X: X.start == F
        train_rows = lambda X: (X.start >= FIRST_FIT) & (X.start <= F - 1)
        fit_rows = lambda X: (X.start >= FIRST_FIT) & (X.start <= F - 2)
        val_rows = lambda X: X.start == F - 1
        test = X0[test_rows(X0)]
        y = test.y.values
        ys.append(y)
        ll = lambda p: -np.log(p[np.arange(len(y)), y])
        base_p = probe.fit_predict(X0[train_rows(X0)], test, base_cols)
        losses["Basis"].append(ll(base_p))
        row = {"season": test.season.iloc[0], "matches": len(test)}
        for name, options in candidates.items():
            opts = options()
            key = choose(opts, fit_rows, val_rows)
            X = builds[key[0]]
            p = probe.fit_predict(X[train_rows(X)], X[test_rows(X)], opts[key])
            losses[name].append(ll(p))
            chosen[name][row["season"]] = str(key[1] if key[1] is not None else key[0])
            row[name] = round(float((ll(p) - ll(base_p)).mean()), 4)
        per_season.append(row)
        print(f"{row['season']}: " + "  ".join(f"{n} {row[n]:+.4f}" for n in candidates))

    base = np.concatenate(losses["Basis"])
    rng = np.random.default_rng(0)
    idx = [rng.integers(0, len(base), len(base)) for _ in range(2000)]
    print(f"\nGesamt: {len(base)} Testspiele, {per_season[0]['season']}..{per_season[-1]['season']}")
    print(f"{'Basis':26s} LogLoss {base.mean():.4f}")
    report = {"test_matches": int(len(base)), "seasons": per_season, "chosen": chosen, "pooled": []}
    for name in candidates:
        cand = np.concatenate(losses[name])
        d = cand - base
        ci = np.percentile([d[i].mean() for i in idx], [2.5, 97.5])
        better = bool(ci[1] < 0)
        ahead = sum(r[name] < 0 for r in per_season)
        report["pooled"].append({"name": name, "log_loss": round(float(cand.mean()), 4), "diff": round(float(d.mean()), 4),
                                 "ci": [round(float(c), 4) for c in ci], "better": better,
                                 "seasons_ahead": f"{ahead}/{len(per_season)}"})
        print(f"{name:26s} LogLoss {cand.mean():.4f}  Δ {d.mean():+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]  "
              f"besser in {ahead}/{len(per_season)} Saisons{'  ✓ Kriterium erfüllt' if better else ''}")
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(f"\ngeschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

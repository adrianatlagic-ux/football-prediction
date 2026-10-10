"""Does chance quality (xG, shots on target) add information beyond Elo + squad value?

    python3 scripts/form_xg_probe.py

Step 2 of docs/form_xg_plan.md, built like scripts/form_probe.py: features
strictly from the state before each match day, one multinomial logistic
regression per variant, so only the features differ. Bundesliga.

  train  2015-16 .. 2021-22 (2014-15, Understat's first season, only warms
         the xG ratings up; every variant is trained on the same matches)
  test   2022-23 .. latest, the same 1,260 matches as form_probe.py

Variants:
  1 base             Elo + squad value
  2 xG average       + xG for/against over the last 10 games (half-life 5),
                     not adjusted for the opponent
  3 xG rating        + attack/defence ratings from xG beside Elo
  4 shot rating      + the same ratings from shots on target
  5 Elo mix          Elo updated from a mix of the result and the xG result
                     (30/50/70 % xG) in place of Elo

The rating speed k, the pull back towards average at a new season and the
mix share are chosen on the training years only: fitted on 2015-16..2019-20,
judged on 2020-21..2021-22, then refitted on all training years and tested
once. Success, fixed in advance: the 95 % bootstrap interval of the log-loss
difference to the base lies entirely below 0.

Writes data/model_reports/form_xg_probe_20261010.json.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.club_data_loader import load_completed_matches  # noqa: E402
from src.club_market_value_policy import DEFAULT_POLICY, MarketValueHistory  # noqa: E402

OUT = ROOT / "data" / "model_reports" / "form_xg_probe_20261010.json"
K_ELO, HA_ELO = 20.0, 60.0
K_GRID = [0.02, 0.05, 0.10, 0.20]
PULL_GRID = [0.0, 0.3, 0.6]
MIX_GRID = [0.3, 0.5, 0.7]
MIN_RATED_GAMES = 5


def load_stats():
    stats = {}
    for path in sorted((ROOT / "data" / "club_stats").glob("bundesliga_*.csv")):
        for r in csv.DictReader(path.open(encoding="utf-8")):
            num = lambda k: float(r[k]) if r[k] not in ("", None) else None
            stats[(r["date"], r["home_team"], r["away_team"])] = {
                "xg": (num("home_xg"), num("away_xg")), "sot": (num("home_sot"), num("away_sot"))}
    return stats


H = load_completed_matches().sort_values("date").reset_index(drop=True)
H["day"] = H.date.astype(str).str[:10]
STATS = load_stats()
MV = MarketValueHistory()


def poisson_result(lh, la, n=10):
    """Expected score (win 1, draw 0.5) of a match with these goal rates."""
    ph = [math.exp(-lh) * lh ** i / math.factorial(i) for i in range(n)]
    pa = [math.exp(-la) * la ** i / math.factorial(i) for i in range(n)]
    win = sum(ph[i] * pa[j] for i in range(n) for j in range(i))
    draw = sum(ph[i] * pa[i] for i in range(n))
    return win + 0.5 * draw


def league_rates(kind):
    """log mean away value and log home advantage, from the training years."""
    vals = [v[kind] for (d, h, a), v in STATS.items() if "2014-08" <= d < "2022-07" and None not in v[kind]]
    home = np.mean([x[0] for x in vals])
    away = np.mean([x[1] for x in vals])
    return math.log(away), math.log(home / away)


class Rating:
    """Attack/defence per team from a chance measure, updated like Elo."""

    def __init__(self, kind, k, pull):
        self.kind, self.k, self.pull = kind, k, pull
        self.mu, self.ha = league_rates(kind)
        self.att, self.dfn = defaultdict(float), defaultdict(float)
        self.games, self.season = defaultdict(int), {}

    def _new_season(self, team, season):
        if self.season.get(team) not in (None, season):
            self.att[team] *= 1 - self.pull
            self.dfn[team] *= 1 - self.pull
        self.season[team] = season

    def expected(self, home, away):
        return (math.exp(self.mu + self.ha + self.att[home] - self.dfn[away]),
                math.exp(self.mu + self.att[away] - self.dfn[home]))

    def features(self, home, away, season, prefix):
        for t in (home, away):
            self._new_season(t, season)
        eh, ea = self.expected(home, away)
        return {f"{prefix}_att_h": self.att[home], f"{prefix}_def_h": self.dfn[home],
                f"{prefix}_att_a": self.att[away], f"{prefix}_def_a": self.dfn[away],
                f"{prefix}_exp_diff": eh - ea,
                f"{prefix}_missing": int(self.games[home] < MIN_RATED_GAMES) + int(self.games[away] < MIN_RATED_GAMES)}

    def update(self, home, away, value):
        if value is None or None in value:
            return
        eh, ea = self.expected(home, away)
        dh, da = value[0] - eh, value[1] - ea
        self.att[home] += self.k * dh
        self.dfn[away] -= self.k * dh
        self.att[away] += self.k * da
        self.dfn[home] -= self.k * da
        self.games[home] += 1
        self.games[away] += 1


def wavg(vals, half_life=5):
    v = np.array(vals, dtype=float)
    if len(v) == 0:
        return 0.0
    w = np.exp(np.log(0.5) / half_life * (len(v) - 1 - np.arange(len(v))))
    return float(w @ v / w.sum())


def build(xg_k, xg_pull, sot_k, sot_pull):
    """One chronological pass; every variant's features per Bundesliga match."""
    elo = {}
    mixes = {w: {} for w in MIX_GRID}
    xg_rating = Rating("xg", xg_k, xg_pull)
    sot_rating = Rating("sot", sot_k, sot_pull)
    recent = defaultdict(lambda: deque(maxlen=10))     # (xG for, xG against)
    rows = []
    for day, games in H.groupby("day", sort=True):
        for r in games.itertuples():
            key = (day, r.home_team, r.away_team)
            if r.competition != "bundesliga":
                continue
            f = {"season": r.season, "y": 0 if r.home_goals > r.away_goals else 1 if r.home_goals == r.away_goals else 2}
            f["elo_diff"] = (elo.get(r.home_team, 1500.0) - elo.get(r.away_team, 1500.0)) / 100
            for w, table in mixes.items():
                f[f"elo_mix{int(w * 100)}"] = (table.get(r.home_team, 1500.0) - table.get(r.away_team, 1500.0)) / 100
            m = MV.features(r.home_team, r.away_team, r.date, DEFAULT_POLICY)
            ratio = m["market_value_ratio"]
            f["log_mv_ratio"] = float(np.log(ratio)) if ratio > 0 else 0.0
            f["mv_missing"] = m["home_market_value_missing"] + m["away_market_value_missing"]
            for side, team in (("h", r.home_team), ("a", r.away_team)):
                g = list(recent[team])
                f[f"{side}_xgf"] = wavg([x[0] for x in g])
                f[f"{side}_xga"] = wavg([x[1] for x in g])
                f[f"{side}_xg_n"] = len(g)
            f.update(xg_rating.features(r.home_team, r.away_team, r.season, "xg"))
            f.update(sot_rating.features(r.home_team, r.away_team, r.season, "sot"))
            rows.append(f)
        changes = defaultdict(float)
        mix_changes = {w: defaultdict(float) for w in MIX_GRID}
        for r in games.itertuples():
            key = (day, r.home_team, r.away_team)
            s = 1.0 if r.home_goals > r.away_goals else 0.0 if r.home_goals < r.away_goals else 0.5
            eh, ea = elo.get(r.home_team, 1500.0), elo.get(r.away_team, 1500.0)
            e = 1 / (1 + 10 ** ((ea - eh - HA_ELO) / 400))
            changes[r.home_team] += K_ELO * (s - e)
            changes[r.away_team] -= K_ELO * (s - e)
            stat = STATS.get(key) if r.competition == "bundesliga" else None
            xg = stat["xg"] if stat else (None, None)
            s_xg = poisson_result(*xg) if None not in xg else None
            for w, table in mixes.items():
                mh, ma = table.get(r.home_team, 1500.0), table.get(r.away_team, 1500.0)
                me = 1 / (1 + 10 ** ((ma - mh - HA_ELO) / 400))
                ms = s if s_xg is None else (1 - w) * s + w * s_xg
                mix_changes[w][r.home_team] += K_ELO * (ms - me)
                mix_changes[w][r.away_team] -= K_ELO * (ms - me)
            if stat:
                xg_rating.update(r.home_team, r.away_team, stat["xg"])
                sot_rating.update(r.home_team, r.away_team, stat["sot"])
                if None not in xg:
                    recent[r.home_team].append((xg[0], xg[1]))
                    recent[r.away_team].append((xg[1], xg[0]))
        for t, d in changes.items():
            elo[t] = elo.get(t, 1500.0) + d
        for w, ch in mix_changes.items():
            for t, d in ch.items():
                mixes[w][t] = mixes[w].get(t, 1500.0) + d
    X = pd.DataFrame(rows)
    X["start"] = X.season.str[:4].astype(int)
    return X


BASE = ["elo_diff", "log_mv_ratio", "mv_missing"]
both = lambda names: [f"{s}_{n}" for s in ("h", "a") for n in names]
RATING = lambda p: [f"{p}_att_h", f"{p}_def_h", f"{p}_att_a", f"{p}_def_a", f"{p}_exp_diff", f"{p}_missing"]


def fit_predict(train, test, cols):
    sc = StandardScaler().fit(train[cols])
    lr = LogisticRegression(C=1.0, max_iter=3000).fit(sc.transform(train[cols]), train.y)
    return lr.predict_proba(sc.transform(test[cols]))


def inner_score(X, cols):
    fit = X[(X.start >= 2015) & (X.start <= 2019)]
    val = X[(X.start >= 2020) & (X.start <= 2021)]
    return log_loss(val.y, fit_predict(fit, val, cols), labels=[0, 1, 2])


def main():
    # Choose k and the season pull for each rating on the training years.
    best = {}
    for kind in ("xg", "sot"):
        scores = {}
        for k in K_GRID:
            for pull in PULL_GRID:
                X = build(k, pull, k, pull)
                scores[(k, pull)] = inner_score(X, BASE + RATING(kind))
        best[kind] = min(scores, key=scores.get)
        print(f"{kind}: chosen k={best[kind][0]}, pull={best[kind][1]} "
              f"(validation log-loss {scores[best[kind]]:.4f})")
    X = build(*best["xg"], *best["sot"])
    mix_scores = {w: inner_score(X, [f"elo_mix{int(w * 100)}", "log_mv_ratio", "mv_missing"]) for w in MIX_GRID}
    best_mix = min(mix_scores, key=mix_scores.get)
    print(f"Elo mix: chosen {int(best_mix * 100)} % xG (validation {mix_scores[best_mix]:.4f})")

    train = X[(X.start >= 2015) & (X.start <= 2021)]
    test = X[X.start >= 2022]
    variants = {
        "1 Basis: Elo + Marktwert": BASE,
        "2 + xG-Durchschnitt (ohne Gegner)": BASE + both(["xgf", "xga"]),
        "3 + xG-Bewertung neben Elo": BASE + RATING("xg"),
        "4 + Schuss-Bewertung neben Elo": BASE + RATING("sot"),
        "3+4 + beide Bewertungen": BASE + RATING("xg") + RATING("sot"),
    }
    for w in MIX_GRID:
        mark = " (auf Training gewählt)" if w == best_mix else ""
        variants[f"5 Elo-Mischung {int(w * 100)} % xG{mark}"] = [f"elo_mix{int(w * 100)}", "log_mv_ratio", "mv_missing"]
    print(f"\nTrain {len(train)} BL-Spiele, Test {len(test)} BL-Spiele ({test.season.min()}..{test.season.max()})")
    y = test.y.values
    probs = {name: fit_predict(train, test, cols) for name, cols in variants.items()}
    ref = probs["1 Basis: Elo + Marktwert"]
    ll = lambda p: -np.log(p[np.arange(len(y)), y])
    rng = np.random.default_rng(0)
    idx = [rng.integers(0, len(test), len(test)) for _ in range(2000)]
    report = {"chosen": {"xg": best["xg"], "sot": best["sot"], "mix": best_mix},
              "train_matches": len(train), "test_matches": len(test), "variants": []}
    for name, p in probs.items():
        d = ll(p) - ll(ref)
        ci = np.percentile([d[i].mean() for i in idx], [2.5, 97.5])
        better = bool(ci[1] < 0)
        report["variants"].append({"name": name, "log_loss": round(log_loss(y, p, labels=[0, 1, 2]), 4),
                                   "accuracy": round(float((p.argmax(1) == y).mean()), 3),
                                   "diff": round(float(d.mean()), 4), "ci": [round(float(c), 4) for c in ci],
                                   "better": better})
        print(f"{name:42s} LogLoss {log_loss(y, p, labels=[0, 1, 2]):.4f}  Acc {(p.argmax(1) == y).mean():.3f}  "
              f"Δ {d.mean():+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]{'  ✓ besser' if better else ''}")
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(f"\ngeschrieben: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

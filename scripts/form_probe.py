"""Does recent form add information beyond Elo + squad value? Walk-forward probe.

Features are built strictly chronologically (state before each match date).
Train: Bundesliga 2013-14 .. 2021-22. Test: Bundesliga 2022-23 .. latest.
Multinomial logistic regression, so only the information in the features
differs between variants, not the model. The reference point for the planned
xG ratings (docs/form_xg_plan.md).

    python3 scripts/form_probe.py
"""
import sys
from collections import defaultdict, deque
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.club_data_loader import load_completed_matches
from src.club_market_value_policy import DEFAULT_POLICY, MarketValueHistory

H = load_completed_matches().sort_values("date").reset_index(drop=True)
mv = MarketValueHistory()
elo, K, HA = {}, 20.0, 60.0
games = defaultdict(lambda: deque(maxlen=10))  # (pts, gd, resid_score, shots-free)


def exp_score(h, a):
    return 1 / (1 + 10 ** ((a - h - HA) / 400))


def wavg(vals, n=None, half_life=None):
    v = np.array(vals[-n:] if n else vals, dtype=float)
    if len(v) == 0:
        return 0.0
    if half_life is None:
        return float(v.mean())
    w = np.exp(np.log(0.5) / half_life * (len(v) - 1 - np.arange(len(v))))
    return float(w @ v / w.sum())


rows = []
for date, day in H.groupby("date", sort=True):
    for r in day.itertuples():
        f = {"date": date, "competition": r.competition, "season": r.season,
             "y": 0 if r.home_goals > r.away_goals else 1 if r.home_goals == r.away_goals else 2}
        eh, ea = elo.get(r.home_team, 1500.0), elo.get(r.away_team, 1500.0)
        f["elo_diff"] = (eh - ea) / 100
        m = mv.features(r.home_team, r.away_team, date, DEFAULT_POLICY)
        ratio = m["market_value_ratio"]
        f["log_mv_ratio"] = float(np.log(ratio)) if ratio > 0 else 0.0
        f["mv_missing"] = m["home_market_value_missing"] + m["away_market_value_missing"]
        for side, team in (("h", r.home_team), ("a", r.away_team)):
            g = list(games[team])
            pts = [x[0] for x in g]; gd = [x[1] for x in g]; res = [x[2] for x in g]
            f[f"{side}_pts10_hl5"] = wavg(pts, 10, 5)       # production-style form
            f[f"{side}_gd10_hl5"] = wavg(gd, 10, 5)
            f[f"{side}_pts10_hl2"] = wavg(pts, 10, 2)       # "weight recent games more"
            f[f"{side}_gd10_hl2"] = wavg(gd, 10, 2)
            f[f"{side}_pts3"] = wavg(pts, 3); f[f"{side}_pts5"] = wavg(pts, 5)
            f[f"{side}_gd3"] = wavg(gd, 3); f[f"{side}_gd5"] = wavg(gd, 5)
            f[f"{side}_res5"] = wavg(res, 5); f[f"{side}_res10"] = wavg(res, 10)  # vs. Elo expectation
        rows.append(f)
    changes = defaultdict(float)
    for r in day.itertuples():
        eh, ea = elo.get(r.home_team, 1500.0), elo.get(r.away_team, 1500.0)
        e = exp_score(eh, ea)
        s = 1.0 if r.home_goals > r.away_goals else 0.0 if r.home_goals < r.away_goals else 0.5
        changes[r.home_team] += K * (s - e); changes[r.away_team] -= K * (s - e)
        ph = 3 if s == 1 else 1 if s == 0.5 else 0
        pa = 3 if s == 0 else 1 if s == 0.5 else 0
        games[r.home_team].append((ph, r.home_goals - r.away_goals, s - e))
        games[r.away_team].append((pa, r.away_goals - r.home_goals, (1 - s) - (1 - e)))
    for t, d in changes.items():
        elo[t] = elo.get(t, 1500.0) + d

X = pd.DataFrame(rows)
bl = X[X.competition == "bundesliga"].copy()
bl["start"] = bl.season.str[:4].astype(int)
train = bl[(bl.start >= 2013) & (bl.start <= 2021)]
test = bl[bl.start >= 2022]
base = ["elo_diff", "log_mv_ratio", "mv_missing"]
both = lambda names: [f"{s}_{n}" for s in ("h", "a") for n in names]
variants = {
    "Basis: Elo + Marktwert": base,
    "+ Form wie heute (10 Spiele, HWZ 5)": base + both(["pts10_hl5", "gd10_hl5"]),
    "+ Form stärker gewichtet (HWZ 2)": base + both(["pts10_hl2", "gd10_hl2"]),
    "+ letzte 3 und 5 Spiele": base + both(["pts3", "pts5", "gd3", "gd5"]),
    "+ Form gegen Erwartung (5/10)": base + both(["res5", "res10"]),
    "nur Form wie heute, ohne Elo/MW": both(["pts10_hl5", "gd10_hl5"]),
}
print(f"Train {len(train)} BL-Spiele, Test {len(test)} BL-Spiele ({test.season.min()}..{test.season.max()})")
rng = np.random.default_rng(0)
idx = [rng.integers(0, len(test), len(test)) for _ in range(1000)]
probs = {}
for name, cols in variants.items():
    sc = StandardScaler().fit(train[cols])
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(train[cols]), train.y)
    probs[name] = lr.predict_proba(sc.transform(test[cols]))
y = test.y.values
ref = probs["Basis: Elo + Marktwert"]
ll = lambda p: -np.log(p[np.arange(len(y)), y])
for name, p in probs.items():
    d = ll(p) - ll(ref)
    ci = np.percentile([d[i].mean() for i in idx], [2.5, 97.5])
    acc = (p.argmax(1) == y).mean()
    print(f"{name:40s} LogLoss {log_loss(y, p, labels=[0,1,2]):.4f}  Acc {acc:.3f}  Δ vs Basis {d.mean():+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]")

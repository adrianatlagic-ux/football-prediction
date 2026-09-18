"""Empirically find the recency half-life (days) that maximizes accuracy for
the club model's sample weighting - same idea as tune_club_blend.py but for
_compute_sample_weights' half_life_days instead of the Poisson blend ratio."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss

from src.club_data_loader import load_completed_matches
from src.club_feature_engineering import build_features, get_feature_columns, encode_result
from src.models.ensemble_model import EnsemblePredictor

CLASSES = ["H", "D", "A"]

history = load_completed_matches()
history["result"] = history.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)

features = build_features(history)
feature_cols = get_feature_columns(features)
split = int(len(features) * 0.8)
train, test = features.iloc[:split], features.iloc[split:]
df_train = history.iloc[:split].reset_index(drop=True)

y_true = test["result"].values
print(f"Test-Spiele: {len(y_true)}\n")
print(f"{'Halbwertszeit':>15} {'Accuracy':>10} {'LogLoss':>9}")

best = None
for half_life_days in [90, 180, 270, 365, 545, 730, 1095]:
    ref_date = pd.Timestamp.now()
    days_ago = (ref_date - df_train["date"]).dt.days.clip(lower=0).values
    weights = np.exp(-np.log(2) / half_life_days * days_ago)
    weights = weights / weights.mean()

    model = EnsemblePredictor()
    model.fit(train[feature_cols], train["result"], sample_weight=weights)

    proba = model.predict_proba(test[feature_cols])
    pred = np.array(CLASSES)[proba.argmax(axis=1)]
    acc = accuracy_score(y_true, pred)
    ll = log_loss(y_true, proba, labels=CLASSES)

    flag = ""
    if best is None or acc > best[1]:
        best = (half_life_days, acc, ll)
        flag = "  <-- beste Accuracy"
    print(f"{half_life_days:>13}d {acc:>10.1%} {ll:>9.4f}{flag}")

print(f"\nBeste Halbwertszeit: {best[0]} Tage: {best[1]:.1%} (LogLoss {best[2]:.4f})")

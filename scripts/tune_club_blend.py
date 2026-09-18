"""Empirically find the classifier/Poisson blend weight that maximizes
accuracy for the club model - same method as scripts/tune_blend.py for the
WC model, applied to data/club_football_results.csv instead."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from sklearn.metrics import accuracy_score, log_loss

from src.club_data_loader import load_completed_matches
from src.club_feature_engineering import build_features, get_feature_columns, encode_result
from src.poisson_model import predict_scorelines
from src.club_predictor import ClubFootballPredictor

CLASSES = ["H", "D", "A"]

history = load_completed_matches()
history["result"] = history.apply(lambda r: encode_result(r["home_goals"], r["away_goals"]), axis=1)

features = build_features(history)
feature_cols = get_feature_columns(features)
split = int(len(features) * 0.8)
test = features.iloc[split:].reset_index(drop=True)
df_test = history.iloc[split:].reset_index(drop=True)

p = ClubFootballPredictor(model_path=Path("club_model.joblib"))
p._history = history
p._feature_cols = feature_cols

X = test[feature_cols]
clf_proba = p.model.predict_proba(X)

poi_proba = np.zeros_like(clf_proba)
for i, row in df_test.iterrows():
    try:
        sc = predict_scorelines(history, row["home_team"], row["away_team"])
        poi_proba[i] = [sc["probability_home_win"], sc["probability_draw"], sc["probability_away_win"]]
    except Exception:
        poi_proba[i] = clf_proba[i]

y_true = test["result"].values

print(f"Test-Spiele: {len(y_true)}   (echte Draw-Rate: {(y_true=='D').mean():.1%})\n")
print(f"{'Poisson-Anteil':>16} {'Accuracy':>10} {'LogLoss':>9} {'ø Draw-Pred':>12}")
best = None
for w in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
    blend = (1 - w) * clf_proba + w * poi_proba
    blend = blend / blend.sum(axis=1, keepdims=True)
    pred = np.array(CLASSES)[blend.argmax(axis=1)]
    acc = accuracy_score(y_true, pred)
    ll = log_loss(y_true, blend, labels=CLASSES)
    mean_draw = blend[:, 1].mean()
    flag = ""
    if best is None or acc > best[1]:
        best = (w, acc, ll)
        flag = "  <-- beste Accuracy"
    print(f"{w:>15.0%} {acc:>10.1%} {ll:>9.4f} {mean_draw:>11.1%}{flag}")

print(f"\nBeste Accuracy bei Poisson-Anteil {best[0]:.0%}: {best[1]:.1%} (LogLoss {best[2]:.4f})")

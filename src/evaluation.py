from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss, classification_report, confusion_matrix


def evaluate(y_true: pd.Series, y_pred: np.ndarray, y_proba: np.ndarray | None = None) -> dict:
    report = classification_report(y_true, y_pred, labels=["H", "D", "A"], output_dict=True, zero_division=0)
    metrics = {
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "per_class": report,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=["H", "D", "A"]).tolist(),
    }
    if y_proba is not None:
        encoded = np.array([{"H": 0, "D": 1, "A": 2}[v] for v in y_true])
        metrics["log_loss"] = round(log_loss(encoded, y_proba, labels=[0, 1, 2]), 4)
        metrics["brier_score"] = round(float(np.mean(np.sum((np.asarray(y_proba) - np.eye(3)[encoded]) ** 2, axis=1))), 4)
    return metrics


def print_report(metrics: dict) -> None:
    print(f"\nAccuracy : {metrics['accuracy']:.1%}")
    if "log_loss" in metrics:
        print(f"Log-Loss : {metrics['log_loss']:.4f}")
    print("\nConfusion Matrix (rows=actual, cols=predicted) [H, D, A]:")
    for row in metrics["confusion_matrix"]:
        print("  ", row)
    print()
    for cls, vals in metrics["per_class"].items():
        if isinstance(vals, dict):
            print(f"  {cls:5s}  precision={vals['precision']:.2f}  recall={vals['recall']:.2f}  f1={vals['f1-score']:.2f}")

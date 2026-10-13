"""Train the production club model on every match so far and save it.

    python3 scripts/train_club_verified.py club_model_v3.joblib

The same recipe the evaluations use (src/club_backtest.CalibratedClubModel on
src/club_features_v3, Poisson blend, temperature calibration), fitted with a
cutoff after the last result, as the artifact the API loads
(src/club_predictor.DEFAULT_MODEL_PATH). The calibration window needs the
dated Poisson probabilities only; they are computed for the last four years,
which covers the widest calibration window CalibratedClubModel falls back to
in the off-season (a shorter span left its first days without values and the
temperature fit ran on missing numbers).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.club_backtest import CalibratedClubModel, poisson_for_dates  # noqa: E402
from src.club_data_loader import load_completed_matches  # noqa: E402
from src.club_features_v3 import FEATURE_VERSION, build_features, prepare_history  # noqa: E402
from src.club_predictor import ClubFootballPredictor  # noqa: E402


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "club_model_v3.joblib")
    history = prepare_history(load_completed_matches())
    X = build_features(history)
    cutoff = max(pd.Timestamp.now().normalize(), history.date.max() + pd.Timedelta(days=1))
    needed = history[history.date >= cutoff - pd.Timedelta(days=4 * 365)]
    print(f"{len(history)} matches, features v{FEATURE_VERSION} ({X.shape[1]} columns); "
          f"Poisson for {len(needed)} matches", flush=True)
    scores = poisson_for_dates(history, needed)
    pp = np.full((len(history), 3), np.nan)
    for idx, s in scores.items():
        pp[idx] = [s[k] for k in ("probability_home_win", "probability_draw", "probability_away_win")]
    bundle = CalibratedClubModel().fit(history, X, cutoff, pp)
    window = history[(history.date >= bundle.metadata["calibration_start"]) & (history.date < cutoff)]
    if np.isnan(pp[window.index]).any():
        raise SystemExit("Poisson probabilities missing in the calibration window")
    predictor = ClubFootballPredictor().use_verified_bundle(history, bundle)
    predictor.save(out)
    print(f"saved {out}: {bundle.metadata}")


if __name__ == "__main__":
    main()

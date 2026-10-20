"""Fail the image build if production model files or inference are invalid."""
from pathlib import Path
import hashlib
import json
import math
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPECTED_MODELS = {"club_model_v3.joblib", "model.joblib"}


def verify_files(root=ROOT):
    manifest = json.loads((root / "model-manifest.json").read_text())
    if set(manifest["models"]) != EXPECTED_MODELS:
        raise ValueError("Manifest must contain both production models")
    for name, entry in manifest["models"].items():
        path = root / name
        if not path.is_file():
            raise ValueError(f"Missing model: {name}; run git lfs pull")
        with path.open("rb") as file:
            if file.read(100).startswith(b"version https://git-lfs.github.com/spec/"):
                raise ValueError(f"Unresolved Git LFS pointer: {name}; run git lfs pull")
        if path.stat().st_size != entry["size_bytes"]:
            raise ValueError(f"Wrong model size: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Model checksum mismatch: {name}")


def verify_predictions():
    from sklearn.exceptions import InconsistentVersionWarning
    from src.club_predictor import ClubFootballPredictor
    from src.predictor import FootballPredictor

    warnings.filterwarnings("error", category=InconsistentVersionWarning)
    warnings.filterwarnings("error", message=r".*serialized model.*", category=UserWarning)
    samples = [
        (ClubFootballPredictor, "club_model_v3.joblib", "Bayern Munich", "Borussia Dortmund"),
        (FootballPredictor, "model.joblib", "Germany", "France"),
    ]
    for cls, filename, home, away in samples:
        predictor = cls(model_path=ROOT / filename)
        if not predictor._trained:
            raise ValueError(f"Model not trained: {filename}")
        result = predictor.predict_match(home, away)
        probabilities = [result[key] for key in (
            "probability_home_win", "probability_draw", "probability_away_win")]
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in probabilities):
            raise ValueError(f"Invalid prediction: {filename}")
        if abs(sum(probabilities) - 1) > 0.002:
            raise ValueError(f"Probabilities do not sum to one: {filename}")
        print(f"Verified {filename}: loads and predicts successfully")


if __name__ == "__main__":
    verify_files()
    verify_predictions()

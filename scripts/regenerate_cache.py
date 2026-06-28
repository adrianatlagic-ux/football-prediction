"""Regenerate all cached predictions with the current model.

Reads each cached JSON (for its team names + match_id), re-runs predict_match,
and writes the fresh prediction back. Keeps the exact same files/ids so the
website serves consistent, up-to-date predictions.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor

CACHE_DIR = Path(__file__).parent.parent / "data" / "predictions_cache"

predictor = FootballPredictor(model_path="model.joblib")
files = sorted(CACHE_DIR.glob("*.json"))
print(f"Regeneriere {len(files)} Vorhersagen mit dem neuen Modell...\n")

for f in files:
    old = json.loads(f.read_text(encoding="utf-8"))
    home, away = old["home_team"], old["away_team"]
    old_draw = old.get("probability_draw", 0)
    fresh = predictor.predict_match(home, away)
    f.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {home} vs {away}:  Draw {old_draw:.0%} -> {fresh['probability_draw']:.0%}")

print(f"\n{len(files)} Vorhersagen aktualisiert.")

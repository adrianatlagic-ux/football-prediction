"""Regenerate all cached predictions with the current model.

Reads each cached JSON (for its team names + match_id), re-runs predict_match,
and writes the fresh prediction back. Keeps the exact same files/ids so the
website serves consistent, up-to-date predictions.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor
from src.scenario_agent import generate_ai_scenario

CACHE_DIR = Path(__file__).parent.parent / "data" / "predictions_cache"
KNOCKOUT_SUFFIX = re.compile(r"_(r\d+|qf|sf|final)$")

predictor = FootballPredictor(model_path="model.joblib")
files = sorted(CACHE_DIR.glob("*.json"))
print(f"Regeneriere {len(files)} Vorhersagen mit dem neuen Modell...\n")

for f in files:
    old = json.loads(f.read_text(encoding="utf-8"))
    home, away = old["home_team"], old["away_team"]
    old_draw = old.get("probability_draw", 0)
    is_knockout = bool(KNOCKOUT_SUFFIX.search(f.stem))
    fresh = predictor.predict_match(home, away)
    ai_scenario = generate_ai_scenario(fresh, home, away, is_knockout=is_knockout)
    if ai_scenario:
        fresh["score_prediction"]["betting_markets"]["scenario"] = ai_scenario
    f.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {home} vs {away}:  Draw {old_draw:.0%} -> {fresh['probability_draw']:.0%}")

print(f"\n{len(files)} Vorhersagen aktualisiert.")

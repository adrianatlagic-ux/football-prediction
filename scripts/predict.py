import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor

parser = argparse.ArgumentParser()
parser.add_argument("--home", required=True, help="Heimteam (z.B. 'Germany')")
parser.add_argument("--away", required=True, help="Auswärtsteam (z.B. 'Spain')")
parser.add_argument("--model", default="model.joblib")
args = parser.parse_args()

if not Path(args.model).exists():
    print("Modell nicht gefunden. Bitte zuerst: python scripts/train.py")
    sys.exit(1)

predictor = FootballPredictor(model_path=args.model)
r = predictor.predict_match(args.home, args.away, neutral=True)

print(f"\n{'='*45}")
print(f"  {r['home_team']}  vs  {r['away_team']}")
print(f"{'='*45}")
print(f"  Vorhersage  : {r['prediction_label']}")
print(f"  Heimsieg    : {r['probability_home_win']:.1%}")
print(f"  Unentschieden: {r['probability_draw']:.1%}")
print(f"  Auswärtssieg: {r['probability_away_win']:.1%}")
print(f"{'='*45}\n")

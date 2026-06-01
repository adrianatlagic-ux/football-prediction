import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor

RESULT_LABEL = {"H": "Home Win", "D": "Draw", "A": "Away Win"}


def main():
    parser = argparse.ArgumentParser(description="Predict a football match result")
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--model", type=str, default="model.joblib")
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"Model not found. Train first: python scripts/train.py")
        sys.exit(1)

    predictor = FootballPredictor(model_path=model_path)
    result = predictor.predict_match(args.home, args.away)

    print(f"\n{'='*40}")
    print(f"  {result['home_team']}  vs  {result['away_team']}")
    print(f"{'='*40}")
    print(f"  Prediction : {RESULT_LABEL[result['prediction']]}")
    print(f"  Home Win   : {result['probability_home_win']:.1%}")
    print(f"  Draw       : {result['probability_draw']:.1%}")
    print(f"  Away Win   : {result['probability_away_win']:.1%}")
    print(f"{'='*40}\n")


if __name__ == "__main__":
    main()

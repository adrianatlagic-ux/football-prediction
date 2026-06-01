import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor
from src.evaluation import print_report


def main():
    parser = argparse.ArgumentParser(description="Train the football prediction model")
    parser.add_argument("--data", type=str, default=None)
    parser.add_argument("--out", type=str, default="model.joblib")
    parser.add_argument("--test-size", type=float, default=0.2)
    args = parser.parse_args()

    print("Training football prediction model...")
    predictor = FootballPredictor()
    metrics = predictor.train(data_path=args.data, test_size=args.test_size)
    print_report(metrics)
    predictor.save(args.out)
    print(f"\nModel saved to {args.out}")


if __name__ == "__main__":
    main()

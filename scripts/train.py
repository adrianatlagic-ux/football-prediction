import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor
from src.evaluation import print_report

print("Lade echte Länderspieldaten (seit 1990)...")
predictor = FootballPredictor()
metrics = predictor.train(since_year=1990)
print_report(metrics)
predictor.save("model.joblib")
print("\nModell gespeichert: model.joblib")

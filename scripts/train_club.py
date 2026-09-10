import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.club_predictor import ClubFootballPredictor
from src.evaluation import print_report

print("Lade Klub-Fußballdaten (Champions League + Premier League)...")
predictor = ClubFootballPredictor()
metrics = predictor.train()
print_report(metrics)
predictor.save("club_model.joblib")
print("\nModell gespeichert: club_model.joblib")

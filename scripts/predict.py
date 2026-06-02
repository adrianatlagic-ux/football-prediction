import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor

parser = argparse.ArgumentParser()
parser.add_argument("--home", required=True)
parser.add_argument("--away", required=True)
parser.add_argument("--model", default="model.joblib")
args = parser.parse_args()

if not Path(args.model).exists():
    print("Modell nicht gefunden. Bitte zuerst: python scripts/train.py")
    sys.exit(1)

predictor = FootballPredictor(model_path=args.model)
r = predictor.predict_match(args.home, args.away, neutral=True)
e = r["explanation"]
s = r["score_prediction"]

w = 50
print(f"\n{'='*w}")
print(f"  {r['home_team']}  vs  {r['away_team']}")
print(f"{'='*w}")
print(f"  VORHERSAGE    : {r['prediction_label'].upper()}")
print(f"  Heimsieg      : {r['probability_home_win']:.1%}")
print(f"  Unentschieden : {r['probability_draw']:.1%}")
print(f"  Auswärtssieg  : {r['probability_away_win']:.1%}")

print(f"\n--- WAHRSCHEINLICHSTES ERGEBNIS ---")
print(f"  ⚽ {s['most_likely_score']}  (xG: {s['home_xg']} : {s['away_xg']})")
print(f"\n  Top 5 Ergebnisse:")
for sc in s["top_scorelines"]:
    bar = "█" * int(sc["probability"] * 100)
    print(f"    {sc['score']}  {bar:<18}  {sc['probability']*100:.1f}%")

print(f"\n--- WARUM? ---")
print(f"\n  FIFA-Ranking:")
for team, rank in e["fifa_ranking"].items():
    pts = e["fifa_points"][team]
    print(f"    {team:20s}  Rang #{rank:<4}  ({pts} Pkt)")

print(f"\n  Form (letzte 10 Spiele):")
for team, pts in e["form_last_10_avg_pts"].items():
    wr = e["win_rate_last_10"][team]
    print(f"    {team:20s}  Ø {pts} Pkt/Spiel  |  Siege: {wr}")

print(f"\n  Tore (letzte 10 Spiele):")
for team in [r['home_team'], r['away_team']]:
    scored = e["avg_goals_scored"][team]
    conceded = e["avg_goals_conceded"][team]
    cs = e["clean_sheet_rate"][team]
    print(f"    {team:20s}  Ø {scored} geschossen  |  Ø {conceded} kassiert  |  Zu-Null: {cs}")

print(f"\n  Head-to-Head:")
h2h = e["h2h_last_10"]
total = h2h["total_h2h_games"]
if total == 0:
    print(f"    Keine gemeinsamen Spiele in der Historie")
else:
    for key, val in h2h.items():
        if key != "total_h2h_games":
            print(f"    {key:30s} {val}")
    print(f"    Gesamt: {total} Spiele")

print(f"{'='*w}\n")

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
f = r["game_flow"]

w = 54
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

print(f"\n--- SPIELVERLAUF ---")
print(f"  Matchtyp    : {f['match_type']}")
print(f"  Beschreibung: {f['match_description']}")
dom = f['dominance_index']
dom_team = r['home_team'] if dom > 0 else r['away_team']
dom_bar = "█" * int(abs(dom) * 10)
print(f"  Dominanz    : {dom_team} +{abs(dom):.2f}  {dom_bar}")

print(f"\n  Erstes Tor (erwartet ~{f['first_goal']['expected_minute']}.min):")
for key, val in f["first_goal"].items():
    if key != "expected_minute" and isinstance(val, float):
        bar = "█" * int(val * 20)
        print(f"    {key:30s} {bar:<14} {val:.1%}")

print(f"\n  Halbzeit-xG:")
for team, xg in f["halftime_xg"].items():
    print(f"    {team:25s}  {xg:.2f} xG")

print(f"\n  Wahrscheinlichste Halbzeitstände:")
for ht in f["top_halftime_scores"][:3]:
    bar = "█" * int(ht["probability"] * 60)
    print(f"    {ht['score']}  {bar:<14}  {ht['probability']:.1%}")

print(f"\n  Torwahrscheinlichkeit pro 15 Minuten:")
for window, teams in f["goal_timing"].items():
    vals = list(teams.values())
    home_bar = "▓" * int(vals[0] * 40)
    away_bar = "░" * int(vals[1] * 40)
    print(f"    {window}  {home_bar}{away_bar}  ({vals[0]:.2f} | {vals[1]:.2f})")

print(f"\n  Comeback-Wahrscheinlichkeit:")
for team, prob in f["comeback_probability"].items():
    bar = "█" * int(prob * 100)
    print(f"    {team:25s}  {bar:<10}  {prob:.1%}")

print(f"\n  Dramatik (Tor nach 75.):  {f['late_drama_probability']:.1%}")

if f["match_stories"]:
    print(f"\n--- WAHRSCHEINLICHSTE SZENARIEN ---")
    for i, story in enumerate(f["match_stories"], 1):
        print(f"  {i}. {story['szenario']} ({story['wahrscheinlichkeit']:.1%})")
        print(f"     {story['beschreibung']}")

print(f"\n--- WARUM? ---")
print(f"\n  FIFA-Ranking:")
for team, rank in e["fifa_ranking"].items():
    pts = e["fifa_points"][team]
    print(f"    {team:25s}  Rang #{rank:<4}  ({pts} Pkt)")

print(f"\n  Form (letzte 10 Spiele):")
for team, pts in e["form_last_10_avg_pts"].items():
    wr = e["win_rate_last_10"][team]
    print(f"    {team:25s}  Ø {pts} Pkt/Spiel  |  Siege: {wr}")

print(f"\n  Tore (letzte 10 Spiele):")
for team in [r['home_team'], r['away_team']]:
    scored   = e["avg_goals_scored"][team]
    conceded = e["avg_goals_conceded"][team]
    cs       = e["clean_sheet_rate"][team]
    print(f"    {team:25s}  Ø {scored} geschossen  |  Ø {conceded} kassiert  |  Zu-Null: {cs}")

print(f"\n  Head-to-Head:")
h2h   = e["h2h_last_10"]
total = h2h["total_h2h_games"]
if total == 0:
    print(f"    Keine gemeinsamen Spiele in der Historie")
else:
    for key, val in h2h.items():
        if key != "total_h2h_games":
            print(f"    {key:35s} {val}")
    print(f"    Gesamt: {total} Spiele")

print(f"{'='*w}\n")

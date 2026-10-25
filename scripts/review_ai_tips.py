"""Offline AI diary: python scripts/review_ai_tips.py --log LOG --results RESULTS."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ai_tip_review import report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--json-output', type=Path)
    args = parser.parse_args()
    entries = [json.loads(line) for line in args.log.read_text().splitlines() if line.strip()]
    results = json.loads(args.results.read_text())
    output = report(entries, results.get('results', []) if isinstance(results, dict) else results)
    if args.json_output:
        args.json_output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print('KI-Tagebuch – immer 1 € Einsatz pro Tipp; keine neuen API-Aufrufe.')
    print('Kleine Gruppen sind kein Nachweis eines Gewinnvorteils. Erstattungen zählen im ROI mit.')
    names = {'ai': 'KI', 'published': 'Wett-Tipp', 'first_ai': 'Früher KI-Tipp',
             'market_baseline': 'Marktvergleich', 'model_agrees': 'Modell stimmt zu',
             'model_disagrees': 'Modell widerspricht'}
    for g in output['groups']:
        roi = f"{g['roi_pct']:+.1f}%" if g['roi_pct'] is not None else 'offen'
        print(f"{g['week']} | {g['competition']} | {g['version']} | "
              f"{names[g['strategy']]} | {g['market']} | {g['settled']}/{g['bets']} ausgewertet | "
              f"Gewinn {g['profit_units']:+.2f} € | ROI {roi}")
    print('Nicht auswertbar:', output['excluded'])


if __name__ == '__main__':
    main()

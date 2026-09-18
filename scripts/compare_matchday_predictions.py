"""Compare V1 vs V2 predictions against real results.

Reads two prediction JSON files (produced by eval_v1_matchday.py /
eval_v1_season.py in the base repo and eval_v2_matchday.py /
eval_v2_season.py in the codex worktree) and scores both against the
actual final scores.

    python3 scripts/compare_matchday_predictions.py --v1 data/season_2025_26_v1_predictions.json --v2 data/season_2025_26_v2_predictions.json --out data/season_2025_26_comparison.json --label "Bundesliga 2025/26, full season"
"""
import argparse
import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def actual_result(home_goals, away_goals):
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def score(predictions):
    n = len(predictions)
    correct = 0
    log_loss_sum = 0.0
    brier_sum = 0.0
    rows = []
    for p in predictions:
        actual = actual_result(p["home_goals"], p["away_goals"])
        probs = {"H": p["probability_home_win"], "D": p["probability_draw"], "A": p["probability_away_win"]}
        predicted = max(probs, key=probs.get)
        hit = predicted == actual
        correct += hit
        p_actual = max(probs[actual], 1e-12)
        log_loss_sum += -math.log(p_actual)
        brier_sum += sum((probs[k] - (1.0 if k == actual else 0.0)) ** 2 for k in ("H", "D", "A"))
        rows.append({
            "date": p["date"], "match": f"{p['home']} {p['home_goals']}-{p['away_goals']} {p['away']}",
            "actual": actual, "predicted": predicted, "hit": hit,
            "p_home": probs["H"], "p_draw": probs["D"], "p_away": probs["A"],
        })
    return {
        "n": n, "accuracy": correct / n, "log_loss": log_loss_sum / n, "brier": brier_sum / n,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1", default=DATA_DIR / "matchday_1_2_v1_predictions.json", type=Path)
    parser.add_argument("--v2", default=DATA_DIR / "matchday_1_2_v2_predictions.json", type=Path)
    parser.add_argument("--out", default=DATA_DIR / "matchday_1_2_comparison.json", type=Path)
    parser.add_argument("--label", default="Bundesliga 2026/27, matchday 1+2")
    parser.add_argument("--quiet-rows", action="store_true", help="Skip the per-match table (useful for large samples)")
    args = parser.parse_args()

    v1 = json.loads(args.v1.read_text())
    v2 = json.loads(args.v2.read_text())
    assert len(v1) == len(v2), f"prediction count mismatch: v1={len(v1)} v2={len(v2)}"
    for a, b in zip(v1, v2):
        assert a["home"] == b["home"] and a["away"] == b["away"] and a["date"] == b["date"], \
            f"fixture mismatch: {a} vs {b}"

    v1_score = score(v1)
    v2_score = score(v2)

    print(f"{args.label} ({v1_score['n']} matches)")
    print()
    print(f"{'Model':<10} {'Accuracy':>10} {'LogLoss':>10} {'Brier':>10}")
    print(f"{'V1':<10} {v1_score['accuracy']:>9.1%} {v1_score['log_loss']:>10.4f} {v1_score['brier']:>10.4f}")
    print(f"{'V2':<10} {v2_score['accuracy']:>9.1%} {v2_score['log_loss']:>10.4f} {v2_score['brier']:>10.4f}")

    if not args.quiet_rows:
        print()
        print(f"{'Date':<12} {'Match':<45} {'Actual':>6} {'V1':>4} {'V2':>4}")
        for r1, r2 in zip(v1_score["rows"], v2_score["rows"]):
            v1_mark = "OK" if r1["hit"] else "  "
            v2_mark = "OK" if r2["hit"] else "  "
            print(f"{r1['date']:<12} {r1['match']:<45} {r1['actual']:>6} {r1['predicted']:>2}{v1_mark[:1]} {r2['predicted']:>2}{v2_mark[:1]}")

    out = {"v1": {k: v for k, v in v1_score.items() if k != "rows"},
           "v2": {k: v for k, v in v2_score.items() if k != "rows"},
           "v1_rows": v1_score["rows"], "v2_rows": v2_score["rows"]}
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nWrote {args.out}")

    if v1_score["n"] < 50:
        print(f"\nCaveat: {v1_score['n']} matches is a small sample - a few results either way easily swings")
        print("both accuracy and log loss. Treat this as a first data point, not a verdict.")


if __name__ == "__main__":
    main()

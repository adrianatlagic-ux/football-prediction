"""Tally the user's real placed bets (data/placed_bets.jsonl) - the honest ledger.

These are actual bets placed on Tipico following the app's tips, with real
stakes and real outcomes. This is the most truthful measure of whether the tips
make money - real money, real results.

    python3 scripts/placed_bets_summary.py
"""
import json
from pathlib import Path

PATH = Path(__file__).parent.parent / "data" / "placed_bets.jsonl"


def main():
    if not PATH.exists():
        print("Keine platzierten Wetten erfasst.")
        return

    bets = [json.loads(l) for l in PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    won = [b for b in bets if b["result"] == "won"]
    lost = [b for b in bets if b["result"] == "lost"]
    push = [b for b in bets if b["result"] == "push"]

    staked = sum(b["stake"] for b in bets)
    returned = sum(b.get("returned", 0) for b in bets)
    net = returned - staked

    for b in bets:
        mark = {"won": "✅", "lost": "❌", "push": "➖"}.get(b["result"], "?")
        print(f"  {mark} {b['match']:28} {b['pick']:14} @ {b['odds']:.2f} | {b['stake']:.2f}€ -> {b.get('returned',0):.2f}€  ({b['result_score']})")

    decided = len(won) + len(lost)
    print("\n" + "=" * 56)
    print(f"Wetten: {len(bets)}   Gewonnen: {len(won)}  Verloren: {len(lost)}" + (f"  Push: {len(push)}" if push else ""))
    if decided:
        print(f"Trefferquote: {len(won)/decided:.0%}")
    print(f"Eingesetzt: {staked:.2f}€   Zurück: {returned:.2f}€")
    print(f"Gewinn/Verlust: {net:+.2f}€   ROI: {net/staked:+.1%}" if staked else "")


if __name__ == "__main__":
    main()

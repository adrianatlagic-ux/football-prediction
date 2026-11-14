"""The hit rate of the Wett-Tipp, as the landing page shows it.

Counted over every settled Wett-Tipp of the tip logs (data/logs/tips/), the same
way scripts/grade_bets.py counts it: the published tip of the current rule,
graded against the real result, pushes left out. The daily job writes it to
data/jobs/last_hit_rate.json (src/jobs.py) and /site-stats serves it, so the
page never has to grade anything while it loads.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compute(entries: list, results: list) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    from grade_bets import _norm, grade_entries
    finished = {(_norm(r["home_team"]), _norm(r["away_team"]), str(r.get("commence_time"))[:10]): r
                for r in results if r.get("completed") and r.get("home_score") is not None}
    won = lost = 0
    for entry in entries:
        bucket = grade_entries([entry], finished)["buckets"]["bet_tip_ki"]
        won, lost = won + bucket.wins, lost + bucket.losses
    decided = won + lost
    return {"won": won, "lost": lost, "tips": decided, "rate": round(won / decided, 4) if decided else None}

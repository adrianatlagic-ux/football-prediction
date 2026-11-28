import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tip_report  # noqa: E402


def entry(day, home, away, hs, as_, pick, shadow=None, likely=None):
    return {"commence_time": f"{day}T18:00:00Z", "home_team": home, "away_team": away,
            "result": {"home_score": hs, "away_score": as_},
            "agent_eval": {"pick": pick}, "agent_eval_shadow": {"pick": shadow, "pick_probability": 70},
            "likely_pick": likely}


WIN_A = {"market": "1X2", "outcome": "home_win", "team": "Alpha", "best_odds": 2.0, "market_probability": 0.5}
UNDER = {"market": "Over/Under 2.5", "outcome": "Under", "best_odds": 1.8, "market_probability": 0.55}


def test_weeks_hit_rate_market_and_delta():
    entries = [
        entry("2026-11-16", "Alpha", "Bravo", 2, 0, WIN_A, UNDER),     # week 1: tip wins, shadow wins
        entry("2026-11-17", "Alpha", "Bravo", 0, 1, WIN_A, UNDER),     # week 1: tip loses, shadow wins
        entry("2026-11-24", "Alpha", "Bravo", 3, 1, WIN_A, UNDER),     # week 2: tip wins, shadow loses
    ]
    out = tip_report.section_tippers(entries)
    assert "| 16.11.–22.11. | 2 | 1 (50%) | 50% | +0 Pkt. | +0.00 | – |" in out
    assert "| 23.11.–29.11. | 1 | 1 (100%) | 50% | +50 Pkt. | +1.00 | +50 Pkt. |" in out
    assert "**gesamt** | 3 | **2 (67%)**" in out
    differing = tip_report.section_differing(entries)
    assert differing.startswith("3 Spiele mit verschiedenem Tipp: Wett-Tipp trifft 2, Schatten trifft 2.")
    learning = tip_report.section_learning(entries)
    assert "| 16.11.–22.11. | 2 | 100% | 70% | +30 Pkt." in learning


def test_plain_labels():
    assert tip_report.label(WIN_A) == "Sieg Alpha"
    assert tip_report.label(UNDER) == "Unter 2,5"
    assert tip_report.label({"market": "Handicap +1.5", "outcome": "handicap", "team": "Lille"}) == "Handicap Lille +1,5"
    assert tip_report.label({"market": "1X2", "outcome": "draw"}) == "Remis"


def test_a_push_counts_as_neither():
    t = tip_report.Tally()
    t.add(WIN_A, "push")
    assert t.n == 0 and t.pushes == 1

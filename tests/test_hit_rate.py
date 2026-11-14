from src.hit_rate import compute


def _entry(home, odds, tip_market="1X2", status="ok", rule="ki_reviewed_pick_v6"):
    pick = {"market": tip_market, "outcome": "home_win", "team": home, "best_odds": odds}
    return {"home_team": home, "away_team": "Z", "commence_time": "2026-11-01T18:45:00Z",
            "sport_key": "soccer_germany_bundesliga",
            "bet_tip": {"rule": rule, "status": status, "tip": pick if status == "ok" else None,
                        "withheld": None if status == "ok" else pick}}


def _result(home, hs, as_):
    return {"home_team": home, "away_team": "Z", "commence_time": "2026-11-01T18:45Z", "completed": True,
            "home_score": hs, "away_score": as_}


def test_the_hit_rate_counts_only_settled_published_tips():
    entries = [_entry("A", 1.5), _entry("B", 1.5), _entry("C", 1.5), _entry("D", 1.5, status="no_agreement"),
               _entry("E", 1.5)]
    results = [_result("A", 2, 0), _result("B", 0, 1), _result("C", 3, 1), _result("D", 5, 0)]  # E not played
    out = compute(entries, results)
    assert (out["won"], out["lost"], out["tips"]) == (2, 1, 3)
    assert out["rate"] == round(2 / 3, 4)


def test_no_settled_tip_means_no_rate_instead_of_a_zero():
    assert compute([_entry("A", 1.5)], [])["rate"] is None

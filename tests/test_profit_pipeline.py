import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import pytest

from src.bet_audit import snapshot, settlement, evaluate_snapshots, fixture_key
from src.club_features_v3 import build_features, prediction_row, prepare_history
from src.club_market_value_policy import MarketValueHistory
from src.club_backtest import rating_context
from src.poisson_model import predict_scorelines, _compute_team_ratings
from src.evaluation import evaluate
from src.feature_engineering import _goal_stats


def history():
    return prepare_history(pd.DataFrame({"date": pd.date_range("2021-01-01", periods=30, freq="3D"),
        "home_team": ["A", "B", "C"] * 10, "away_team": ["B", "C", "A"] * 10,
        "home_goals": [2, 1, 0, 3, 1] * 6, "away_goals": [1, 1, 2, 0, 0] * 6}))


def tip(market="1X2", outcome="home_win", odds=2.0):
    return {"market": market, "outcome": outcome, "team": "A", "best_odds": odds,
            "model_probability_raw": 0.6, "market_probability": 0.5}


def entry(date="2026-09-18", bet=None):
    bet = bet or tip()
    return {"home_team": "A", "away_team": "B", "sport_key": "soccer_germany_bundesliga",
            "commence_time": date + "T18:00:00Z", "logged_at": date + "T17:45:00Z",
            "combined": {"consensus_pick": bet}, "bets": [bet]}


def result(e, hs=1, aws=0):
    return {**e, "completed": True, "score_scope": "regulation", "home_score": hs,
            "away_score": aws, "observed_at": e["commence_time"].replace("18:00", "20:00")}


@pytest.mark.parametrize("market,outcome,hs,aws,label,units", [
    ("Handicap -0.75", "handicap", 1, 0, "half_win", 0.5),
    ("Handicap +0.25", "handicap", 0, 0, "half_win", 0.5),
    ("Handicap -0.25", "handicap", 0, 0, "half_loss", -0.5),
    ("Handicap +0.75", "handicap", 0, 1, "half_loss", -0.5),
    ("Handicap 0.0", "handicap", 1, 1, "push", 0),
    ("Over/Under 2.0", "Over", 1, 1, "push", 0),
    ("Over/Under 2.25", "Under", 1, 1, "half_win", 0.5),
    ("BTTS", "Yes", 1, 1, "win", 1),
])
def test_settlement(market, outcome, hs, aws, label, units):
    assert settlement(tip(market, outcome), "A", "B", hs, aws) == (label, units)


def test_roi_counts_push_stakes_and_repeated_fixture_dates():
    win = entry(bet=tip("Handicap 0.0", "handicap"))
    push = entry("2026-09-25", tip("Handicap 0.0", "handicap"))
    report = evaluate_snapshots([win, push], [result(win), result(push, 1, 1)])
    group = next(g for g in report["groups"] if g["role"] == "displayed_tip")
    assert group["bets"] == 2 and group["roi"] == 0.5
    assert fixture_key(win) != fixture_key(push)


def test_post_kickoff_and_extra_time_excluded():
    e = entry()
    late = {**e, "logged_at": e["commence_time"]}
    assert snapshot(late, datetime(2026, 9, 18, 18, tzinfo=timezone.utc))[1] == "logged_after_kickoff"
    r = {**result(e), "score_scope": "extra_time"}
    assert not evaluate_snapshots([e], [r])["groups"]


def test_latest_snapshot_chosen_without_looking_at_result():
    early = entry(bet=tip(odds=5))
    latest = {**entry(bet=tip(odds=2)), "logged_at": "2026-09-18T17:55:00Z"}
    report = evaluate_snapshots([early, latest], [result(early)])
    assert report["eligible_fixtures"] == 1
    assert all(r["profit_units"] == 1 for r in report["settlements"])


def test_unknown_teams_not_settled_as_losses():
    e = entry(bet={**tip(), "team": "Unknown"})
    report = evaluate_snapshots([e], [result(e)])
    assert not report["groups"]
    assert report["exclusions"]["invalid_bet_or_quote"] == 2


def test_snapshot_is_append_only_and_deduplicates_identical_content():
    e = entry()
    first, _ = snapshot(e, datetime(2026, 9, 18, 17, 40, tzinfo=timezone.utc))
    second, _ = snapshot(e, datetime(2026, 9, 18, 17, 50, tzinfo=timezone.utc))
    assert first["snapshot_id"] == second["snapshot_id"]
    assert e["logged_at"] == "2026-09-18T17:45:00Z"


def test_season_only_values_not_mislabeled_verified(tmp_path):
    p = tmp_path / "market.csv"
    p.write_text("season_start_year,team,market_value\n2021,A,100000000\n2022,A,200000000\n")
    m = MarketValueHistory(p)
    assert m.value("A", "2022-09-01") is None
    assert m.value("A", "2022-09-01", "lagged_season") == 100000000
    assert m.value("A", "2021-09-01", "lagged_season") is None


def test_future_market_snapshot_never_visible(tmp_path):
    p = tmp_path / "market.csv"
    p.write_text("season_start_year,team,market_value,available_at,source\n2021,A,100000000,2021-10-01T00:00:00Z,test\n")
    m = MarketValueHistory(p)
    assert m.value("A", "2021-09-30") is None
    assert m.value("A", "2021-10-02") == 100000000
    assert m.features("A", "B", "2021-10-02")["home_market_value"] == 0.1


def test_features_resist_future_and_same_day_results():
    df = history()
    df.loc[16, "date"] = df.loc[15, "date"]
    changed = df.copy()
    changed.loc[15:, "home_goals"] = 9
    a, b = build_features(df), build_features(changed)
    pd.testing.assert_frame_equal(a.iloc[:17], b.iloc[:17])
    assert not a.iloc[17:].equals(b.iloc[17:])


def test_fast_training_and_prediction_stats_match_reference():
    df = history()
    features = build_features(df)
    r = df.iloc[20]
    past = df[df.date < r.date]
    reference = _goal_stats(past, r.home_team, "home")
    for k, v in reference.items():
        assert features.iloc[20][k] == pytest.approx(v)
    pred = prediction_row(df, r.home_team, r.away_team, r.date)
    np.testing.assert_allclose(pred.iloc[0], features.iloc[20])


def test_vectorized_ratings_equal_reference():
    df = history()
    _, fast = rating_context(df)
    slow = _compute_team_ratings(df)
    for team in fast:
        np.testing.assert_allclose(fast[team], slow[team])


def test_club_poisson_has_no_world_cup_uplift():
    df = history()
    normal = predict_scorelines(df, "A", "B", club_mode=True)
    knockout = predict_scorelines(df, "A", "B", club_mode=True, is_knockout=True)
    world_cup = predict_scorelines(df, "A", "B")
    assert normal == knockout
    assert world_cup["home_xg"] == pytest.approx(normal["home_xg"] * 1.15, abs=0.02)


def test_log_loss_class_order():
    y = pd.Series(["H", "D", "A"])
    assert evaluate(y, y, np.eye(3))["log_loss"] == 0

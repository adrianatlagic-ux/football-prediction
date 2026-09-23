"""Checks against look-ahead and misleading strategy comparisons."""
import csv
import json
import pytest
from scripts.compare_bet_selection import load_joined, select, summarize, candidates


def bet(outcome="home_win", p=.6, ev=.1, kelly=3, suspicious=False):
    return dict(market="1X2", outcome=outcome, team="Home" if outcome == "home_win" else "Away",
                best_odds=2., probability=p, market_probability=.5, expected_value=ev,
                kelly_stake_pct=kelly, suspicious=suspicious)


def test_warning_excluded_from_every_strategy():
    flagged = bet(p=.8, ev=.6, kelly=20, suspicious=True)
    valid = bet("away_win", p=.2, ev=.05, kelly=2)
    assert all(p is None or p is valid for p in select([flagged, valid]).values())


def test_probability_rule_only_within_declared_ev_band():
    low_p = bet(p=.3, ev=.2, kelly=2)
    high_p = bet("away_win", p=.7, ev=.1, kelly=3)
    assert select([low_p, high_p])["probability_near_ev"] is low_p
    high_p["expected_value"] = .17
    assert select([low_p, high_p])["probability_near_ev"] is high_p


def test_agreement_filters_original_pick_does_not_substitute():
    favorite = bet(p=.7, ev=.04, kelly=1)
    value = bet("away_win", p=.3, ev=.12, kelly=3)
    picks = select([favorite, value])
    assert picks["kelly_baseline"] is value
    assert picks["kelly_model_agrees"] is None


def test_push_stake_counts_in_roi_and_drawdown():
    records = []
    for day, profit, outcome in [("2023-01-01", -1, "loss"), ("2023-01-02", 0, "push"), ("2023-01-03", .5, "half_win")]:
        b = dict(bet(), profit_units=profit, settlement=outcome)
        picks = {name: b for name in select([bet()])}
        records.append(dict(date=day, decisions=picks))
    s = summarize(records)["kelly_baseline"]
    assert s["bets"] == 3
    assert s["roi"] == pytest.approx(-.5 / 3)
    assert s["max_drawdown_end_of_day_units"] == 1


def test_missing_closing_prices_never_fall_back_to_early_odds():
    assert candidates({}, {"B365H": "2", "B365D": "3", "B365A": "4"}, closing=True)[0] is None


def test_join_rejects_post_match_training_and_score_mismatch(tmp_path):
    row = dict(competition="bundesliga", strategy="verified_only/monthly/raw", date="2023-01-01",
               home="Home", away="Away", home_goals=1, away_goals=0, actual="H", probabilities=[.5, .2, .3],
               fit=dict(training_end="2023-01-01", cutoff="2023-01-01"))
    p = tmp_path / "predictions.jsonl"
    p.write_text(json.dumps(row) + "\n")
    q = tmp_path / "D1_2223.csv"
    q.write_text("Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2023,Home,Away,1,0,H\n")
    with pytest.raises(ValueError, match="Training leakage"):
        load_joined(p, tmp_path)
    row["fit"]["training_end"] = "2022-12-31"
    p.write_text(json.dumps(row) + "\n")
    assert len(load_joined(p, tmp_path)[0]) == 1
    q.write_text("Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n01/01/2023,Home,Away,2,0,H\n")
    with pytest.raises(ValueError, match="Score mismatch"):
        load_joined(p, tmp_path)

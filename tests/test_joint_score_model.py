import numpy as np
import pandas as pd
import pytest
from scipy.optimize import check_grad

from src.research_score_model import (HOME, AWAY, OVER, STATS, MAX_GOALS,
    ConditionalScoreModel, align_results, contract_mask, loss_gradient,
    market_grid, poisson_grid, result_probabilities, score_indices)
from scripts.train_joint_score_model import market_inputs, offers, eligible, prior_indices, warning_reasons


def row():
    return {"B365H": "2", "B365D": "3.5", "B365A": "4", "BWH": "2.1", "BWD": "3.4", "BWA": "3.9",
            "B365>2.5": "1.8", "B365<2.5": "2.1", "AHh": "-1.5", "B365AHH": "2.5", "B365AHA": "1.6"}


def test_market_features_ignore_scores_closing_and_pinnacle():
    a = row()
    b = {**a, "FTHG": 9, "B365CH": 1.01, "AvgH": 1.01, "MaxH": 99., "PSH": 1.01, "PSCH": 1.01}
    fa, ha, oa = market_inputs(a)
    fb, hb, ob = market_inputs(b)
    assert fa == fb and oa == ob
    np.testing.assert_array_equal(ha, hb)
    assert fa["IW_missing"] == 1 and fa["BW_missing"] == 0
    assert fa["IW_H"] == pytest.approx(ha[0])


def test_incomplete_book_triplet_not_turned_into_fake_probability():
    a = row(); a["BWA"] = ""
    f, h, _ = market_inputs(a)
    assert f["BW_missing"] == 1
    assert f["BW_H"] == pytest.approx(h[0])


def test_odds_only_prior_has_exact_marginals():
    hda = np.array([[.8, .12, .08], [.15, .3, .55], [.33, .34, .33]])
    over = np.array([.75, .6, .2])
    p = market_grid(hda, over)
    np.testing.assert_allclose(p.sum(axis=1), 1, atol=1e-10)
    np.testing.assert_allclose(result_probabilities(p), hda, atol=1e-9)
    np.testing.assert_allclose(p @ OVER, over, atol=1e-9)
    assert (p > 0).all()


def test_gradient_matches_finite_differences():
    rng = np.random.default_rng(3)
    z = rng.normal(size=(4, 3))
    prior = poisson_grid(np.full((4, 2), 1.4))
    y = score_indices([[0, 0], [1, 1], [3, 1], [0, 2]])
    w = rng.normal(0, .01, size=3 * STATS.shape[1])
    args = (z, np.log(prior), y, .2)
    error = check_grad(lambda w: loss_gradient(w, *args)[0], lambda w: loss_gradient(w, *args)[1], w)
    assert error < 1e-5


def test_model_learns_score_distribution_and_probabilities_are_consistent():
    X = np.arange(30).reshape(-1, 1) / 30
    prior = poisson_grid(np.full((30, 2), 1.5))
    goals = np.tile([3, 0], (30, 1))
    model = ConditionalScoreModel(.1).fit(X, prior, goals)
    p = model.predict(X, prior)
    assert np.mean(p[:, score_indices([[3, 0]])[0]]) > np.mean(prior[:, score_indices([[3, 0]])[0]])
    np.testing.assert_allclose(p.sum(axis=1), 1)
    np.testing.assert_allclose(p @ contract_mask("handicap", "H", -.5), result_probabilities(p)[:, 0])
    np.testing.assert_allclose(p @ contract_mask("handicap", "H", 1.5) + p @ contract_mask("handicap", "A", -1.5), 1)
    np.testing.assert_allclose(p @ contract_mask("totals", "O", 2.5) + p @ contract_mask("totals", "U", 2.5), 1)


def test_zero_correction_is_exact_prior():
    p = poisson_grid(np.array([[1., 2.], [2., 1.]]))
    model = ConditionalScoreModel(None).fit([[0], [1]], p, [[0, 2], [2, 0]])
    np.testing.assert_allclose(model.predict([[0], [1]], p), p)


@pytest.mark.parametrize("goals", [[[21, 0]], [[-1, 2]], [[.5, 2]], [[float("nan"), 1]]])
def test_never_clip_bad_score_labels(goals):
    with pytest.raises(ValueError):
        score_indices(goals)


@pytest.mark.parametrize("line", [0., .25, 1., 1.75])
def test_no_quarter_or_whole_handicap_offers(line):
    a = row(); a["AHh"] = str(line)
    assert len(offers({"odds": a})) == 5
    f, _, _ = market_inputs(a)
    assert f["handicap_missing"] == 1
    with pytest.raises(ValueError):
        contract_mask("handicap", "H", line)


def test_actual_book_handicap_line_and_price_are_preserved():
    h, a = offers({"odds": row()})[-2:]
    assert (h["line"], h["odds"], a["line"], a["odds"]) == (-1.5, 2.5, 1.5, 1.6)


def test_negative_ev_is_allowed_but_warning_excludes():
    p = align_results(poisson_grid([[1.5, 1.5]]), np.array([[.55, .25, .2]]))[0]
    offer = {"kind": "1X2", "side": "H", "line": None, "odds": 1.5, "market_p": .60}
    assert eligible(offer, p)  # .55 * 1.5 - 1 is negative.
    offer["odds"] = 2.5
    assert "ev_above_30pct" in warning_reasons(offer, p)
    assert not eligible(offer, p)


def test_training_never_includes_same_day_or_future():
    history = pd.DataFrame({"date": pd.to_datetime(["2021-01-01", "2021-01-02", "2021-01-03"])})
    np.testing.assert_array_equal(prior_indices(history, "2021-01-02"), [0])

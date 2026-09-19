from copy import deepcopy
import json
import math
import pytest
from src.bet_selection import payout_metrics, combine
from src.game_pick import assess, select_game_pick, market_distribution, adverse_shift


def bet(team="A", probability=.6, market=.55, odds=2.05):
    return {"market": "1X2", "outcome": "home_win" if team == "A" else "away_win", "team": team,
            "best_odds": odds, "bookmaker": "Offer", "bookmaker_key": "offer", "quote_fresh": True,
            "model_probability_raw": probability, "market_probability": market,
            "selection_market_reference": {"books": {"b1": market, "b2": market, "b3": market}},
            **payout_metrics([(odds-1, probability), (-1, 1-probability)])}


def bundle(*bets):
    return {"snapshot_valid": True, "bets": list(bets), "market_favorite": bets[0],
            "model_favorite": bets[0], "recommendation": bets[0]}


def test_favorite_alternative_and_abstention_are_real_decisions():
    favorite = bet()
    alternative = bet("B", .4, .37, 3.3)
    assert select_game_pick(bundle(favorite))["pick"]["team"] == "A"
    switched = select_game_pick(bundle(favorite, alternative))
    assert switched["pick"]["team"] == "B"
    # Same forecasts, worse price: value vanishes, even for the favorite.
    assert select_game_pick(bundle(bet(odds=1.7)))["pick"] is None
    assert combine(bundle(favorite, alternative))["consensus_pick"]["team"] == "B"


def test_price_floor_and_paper_cap():
    decision = assess(bet())
    floor = decision["min_acceptable_odds"]
    assert 0 < decision["paper_stake_pct"] <= 1
    assert assess(bet(odds=floor))["eligible"]
    assert not assess(bet(odds=floor-.01))["eligible"]
    assert decision["stressed_expected_value"] < decision["model_expected_value"]


def test_three_other_books_required_and_source_not_counted_twice():
    b = bet()
    del b["selection_market_reference"]["books"]["b3"]
    assert assess(b)["reason"] == "insufficient_reference_books"
    b["selection_market_reference"]["books"]["offer"] = .55
    assert assess(b)["reason"] == "offered_book_in_reference"


def test_missing_market_data_does_not_inherit_fake_confidence():
    b = bet()
    del b["selection_market_reference"]
    assert select_game_pick(bundle(b))["pick"] is None
    assert select_game_pick({**bundle(bet()), "snapshot_valid": False})["pick"] is None


def test_ai_agreement_does_not_manufacture_an_edge():
    weak = bet(odds=1.7)
    assert combine(bundle(weak), {"pick": weak})["consensus_pick"] is None
    good = bet()
    before = combine(bundle(good))
    after = combine(bundle(good), {"pick": good})
    assert before["selection"] == after["selection"]
    assert not before["agent_agrees"] and after["agent_agrees"]


def test_reference_push_probability_is_not_treated_as_win_probability():
    # DNB: 50% win / 30% push / 20% loss. Market q conditions out pushes.
    d = [(.8, .5), (0, .3), (-1, .2)]
    ref = market_distribution(d, 1.8, .6)
    assert sum(p for r, p in ref if r == 0) == pytest.approx(.3)
    assert sum(p for r, p in ref if r > 0) == pytest.approx(.42)
    # Quarter bet: half gains/losses count as half an exposure.
    d = [(.8, .5), (.4, .3), (-1, .2)]
    ref = market_distribution(d, 1.8, .6)
    w = sum(r*p/.8 for r, p in ref if r > 0)
    loss = sum(-r*p for r, p in ref if r < 0)
    assert w/(w+loss) == pytest.approx(.6)
    assert sum(p for _, p in ref) == pytest.approx(1)


def test_stress_conserves_mass_and_decreases_ev_including_quarters():
    d = [(.8, .5), (.4, .3), (-1, .2)]
    stressed = adverse_shift(d, .03)
    assert sum(p for _, p in stressed) == pytest.approx(1)
    assert all(p >= 0 for _, p in stressed)
    assert sum(r*p for r, p in stressed) == pytest.approx(sum(r*p for r, p in d) - .03*1.8)


def test_more_market_disagreement_cannot_improve_the_score():
    stable = bet()
    divided = deepcopy(stable)
    divided["selection_market_reference"]["books"] = {"b1": .50, "b2": .55, "b3": .60}
    assert assess(divided)["ranking_score"] <= assess(stable)["ranking_score"]


@pytest.mark.parametrize("field,value", [("best_odds", float("nan")), ("payout_distribution", [{"profit": 1, "probability": -1}])])
def test_invalid_pricing_fails_closed(field, value):
    b = bet()
    b[field] = value
    assert not assess(b)["eligible"]


def test_determinism_and_full_json_audit():
    a, b = bet(), bet("B", .4, .37, 3.3)
    first = select_game_pick(bundle(a, b))
    second = select_game_pick(bundle(b, a))
    assert first["pick"] == second["pick"]
    assert len(first["assessments"]) == 2
    json.dumps(first, allow_nan=False)


def test_all_three_api_routes_use_the_actual_selector(monkeypatch):
    from datetime import datetime, timezone, timedelta
    from api import app as api
    now = datetime.now(timezone.utc)
    def book(name, prices):
        return {"key": name, "title": name, "last_update": now.isoformat(), "markets": [
            {"key": "h2h", "outcomes": [{"name": n, "price": p} for n, p in zip(("A", "Draw", "B"), prices)]}]}
    e = {"id": "example", "sport_key": "soccer_germany_bundesliga", "home_team": "A", "away_team": "B",
         "odds_fetched_at": now.isoformat(), "odds_stage": "final",
         "commence_time": (now+timedelta(hours=1)).isoformat(), "bookmakers": [book("offer", [2.05, 3.5, 5.0])] +
         [book(f"ref{i}", [1/(q*1.03) for q in (.55, .25, .2)]) for i in range(3)]}
    p = {"home_team": "A", "away_team": "B", "probability_home_win": .6, "probability_draw": .25, "probability_away_win": .15}
    monkeypatch.setattr(api, "_get_odds", lambda: [e])
    monkeypatch.setattr(api, "_get_prediction_index", lambda: {("a", "b"): p})
    monkeypatch.setattr(api, "_find_cached_prediction", lambda home, away: p)
    monkeypatch.setattr(api, "_refresh_agent_picks", lambda odds: None)
    monkeypatch.setattr(api, "_maybe_prekickoff_refresh", lambda odds: None)
    monkeypatch.setattr(api, "_get_agent_pick", lambda vb: None)
    detail = api.value_bets("A", "B")["combined"]["consensus_pick"]
    summary = api.best_bets()["best_bets"][0]["combined"]["consensus_pick"]
    logged = api.all_bets()["all_bets"][0]["combined"]["consensus_pick"]
    assert detail == summary == logged
    assert detail["team"] == "A"
    assert detail["selection_assessment"]["eligible"]
    assert detail["selection_market_reference"]["book_count"] == 3
    assert "offer" not in detail["selection_market_reference"]["books"]

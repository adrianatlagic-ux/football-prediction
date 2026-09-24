from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import pytest
from src.bet_selection import price_bet, market_consensus, strategy_comparison, combine
from src.bet_research import research_prompt, capture_evidence
from src.bet_audit import evaluate_snapshots
from api import app as api


def prediction():
    return {"home_team": "A", "away_team": "B", "probability_home_win": .5,
            "probability_draw": .3, "probability_away_win": .2,
            "score_prediction": {"home_xg": 1.5, "away_xg": 1.0,
                                 "score_matrix": [[.3, .2], [.5, 0]]}}


def event():
    now = datetime.now(timezone.utc)
    return {"id": "one", "sport_key": "soccer_germany_bundesliga", "home_team": "A", "away_team": "B",
            "commence_time": (now + timedelta(hours=1)).isoformat(), "bookmakers": [
                {"title": "Book", "last_update": now.isoformat(), "markets": [
                    {"key": "h2h", "outcomes": [{"name": "A", "price": 2.2}, {"name": "Draw", "price": 3.4}, {"name": "B", "price": 4.0}]},
                    {"key": "spreads", "outcomes": [{"name": "A", "point": 0.0, "price": 1.8}, {"name": "B", "point": 0.0, "price": 2.1},
                                                      {"name": "A", "point": .25, "price": 1.6}, {"name": "B", "point": -.25, "price": 2.6}]},
                    {"key": "totals", "outcomes": [{"name": "Over", "point": .75, "price": 2.0}, {"name": "Under", "point": .75, "price": 2.0}]}
                ]}]}


@pytest.mark.parametrize("market,outcome,ev,push", [
    ("Handicap 0.0", "handicap", .2, .3),
    ("Handicap +0.25", "handicap", .32, 0),
    ("Handicap -0.25", "handicap", .05, 0),
    ("Handicap +0.5", "handicap", .44, 0),
    ("Handicap -0.5", "handicap", -.1, 0),
    ("Over/Under 1.0", "Under", .24, .7),
])
def test_expected_returns_match_settlement(market, outcome, ev, push):
    b = {"market": market, "outcome": outcome, "team": "A", "best_odds": 1.8}
    p = price_bet(b, prediction(), .99)
    assert p["expected_value"] == pytest.approx(ev)
    assert p["push_probability"] == pytest.approx(push)


def test_dnb_kelly_respects_refunds_and_binary_equivalence():
    b = {"market": "Handicap 0.0", "outcome": "handicap", "team": "A", "best_odds": 1.8}
    priced = price_bet(b, prediction(), .5)
    assert priced["kelly_stake_pct"] == pytest.approx((.5*.8-.2)/(.8*.7)*25)
    p = price_bet({**b, "market": "1X2", "outcome": "home_win", "best_odds": 2.2}, prediction(), .5)
    assert p["kelly_stake_pct"] == pytest.approx((.5*2.2-1)/1.2*25)


def test_legacy_half_distribution_never_used_for_quarter_lines():
    p = prediction()
    del p["score_prediction"]["score_matrix"]
    with pytest.raises(ValueError, match="Full score"):
        price_bet({"market": "Handicap +0.25", "team": "A", "outcome": "handicap", "best_odds": 1.8}, p, .8)


def test_consensus_requires_complete_matching_lines():
    e = event()
    assert market_consensus(e, "spreads", "A", .25) is not None
    e["bookmakers"][0]["markets"][1]["outcomes"][-1]["point"] = -.75
    assert market_consensus(e, "spreads", "A", .25) is None
    e["bookmakers"][0]["markets"][0]["outcomes"].pop()
    assert market_consensus(e, "h2h", "A") is None


def test_api_excludes_quarter_lines_and_rejects_stale_best_offer():
    e = event()
    stale = deepcopy(e["bookmakers"][0])
    stale["last_update"] = (datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
    stale["markets"][0]["outcomes"][0]["price"] = 9.0
    e["bookmakers"].append(stale)
    vb = api._compute_value_bets(prediction(), [e], "A", "B")
    home = next(b for b in vb["bets"] if b["market"] == "1X2" and b["team"] == "A")
    assert home["best_odds"] == 2.2
    assert vb["market_favorite"] == home
    assert not any(b["market"] in {"Over/Under 0.75", "Handicap +0.25", "Handicap -0.25"} for b in vb["bets"])
    assert not any(b["market"] == "Handicap 0.0" for b in vb["bets"])
    e["bookmakers"] = [stale]
    assert api._compute_value_bets(prediction(), [e], "A", "B")["market_favorite"] is None


def test_strategies_abstain_and_reprice_old_ai_pick():
    vb = api._compute_value_bets(prediction(), [event()], "A", "B")
    value = vb["recommendation"]
    # This test controls agreement without imposing any outcome information.
    vb["recommendation_warning"] = False
    vb["model_favorite"] = value
    ai = {"pick": {**value, "best_odds": 99}}
    result = combine(vb, ai)
    confirmed = result["strategy_comparison"]["strategies"]["value_model_ai_v1"]["pick"]
    assert confirmed["best_odds"] == value["best_odds"] != 99
    assert result["market_favorite"] == vb["market_favorite"]
    assert result["consensus_pick"] is None  # one book is insufficient for the new selector
    assert strategy_comparison(vb)["strategies"]["value_model_ai_v1"]["pick"] is None
    assert set(strategy_comparison(vb)["strategies"]) == {"market_favorite_v1", "value_v1", "value_model_ai_v1", "market_model_stress_v1"}


def test_prompt_cannot_reveal_model_or_recommendation():
    now = datetime.now(timezone.utc)
    vb = api._compute_value_bets(prediction(), [event()], "A", "B")
    before = research_prompt(vb, "A", "B", now)
    altered = deepcopy(vb)
    altered["recommendation"] = {"secret": "FORBIDDEN"}
    for b in altered["bets"]:
        b["probability"] = .99999
        b["expected_value"] = 500
    altered["bets"].reverse()
    assert research_prompt(altered, "A", "B", now) == before
    assert "World Cup" not in before and "FORBIDDEN" not in before


def test_research_is_not_automatically_verified():
    evidence = capture_evidence({"facts": [
        {"claim": "Missing player", "source_url": "https://club.test/news", "published_at": "2099-01-01T00:00:00Z"},
        {"claim": "Reported player", "source_url": "https://club.test/news", "published_at": None}
    ]}, ["https://club.test/news"])
    assert evidence["facts"][0]["time_status"] == "future_time_rejected"
    assert not any(f["verified"] for f in evidence["facts"])


def test_ai_cache_distinguishes_return_fixture_and_updates_price():
    vb = api._compute_value_bets(prediction(), [event()], "A", "B")
    key = api._agent_key(vb)
    old = dict(api._agent_picks_cache)
    try:
        api._agent_picks_cache[key] = {"pick": {**vb["market_favorite"], "best_odds": 9}}
        assert api._get_agent_pick(vb)["pick"]["best_odds"] == vb["market_favorite"]["best_odds"]
        assert api._get_agent_pick({**vb, "event_id": "return"}) is None
    finally:
        api._agent_picks_cache.clear()
        api._agent_picks_cache.update(old)


def test_no_ambiguous_reverse_or_substring_event_matches():
    e = event()
    assert api._find_odds_match([e], "B", "A") is None
    assert api._find_odds_match([e, {**e, "id": "two"}], "A", "B") is None
    paris = {**e, "home_team": "Paris Saint Germain"}
    assert api._find_odds_match([paris], "Paris", "B") is None
    assert api._find_odds_match([paris], "Paris Saint-Germain", "B") == paris


@pytest.mark.parametrize("kickoff", [None, "bad date", "2026-09-19T12:00:00"])
def test_invalid_kickoff_fails_closed(kickoff):
    e = {**event(), "commence_time": kickoff}
    assert not api._compute_value_bets(prediction(), [e], "A", "B")["bets"]


def test_strategy_audit_preserves_abstentions_and_fixed_stakes():
    e = event()
    vb = api._compute_value_bets(prediction(), [e], "A", "B")
    logged = {**vb, "logged_at": datetime.now(timezone.utc).isoformat(), "combined": combine(vb)}
    result = {**e, "home_score": 1, "away_score": 0, "completed": True, "score_scope": "regulation",
              "observed_at": (datetime.now(timezone.utc)+timedelta(hours=3)).isoformat()}
    report = evaluate_snapshots([logged], [result])
    market = next(r for r in report["strategies"] if r["strategy"] == "market_favorite_v1")
    confirmed = next(r for r in report["strategies"] if r["strategy"] == "value_model_ai_v1")
    assert market["settled_bets"] == 1 and market["roi"] == pytest.approx(1.2)
    assert confirmed["no_bets"] == 1 and confirmed["roi"] is None
    json.dumps(report, allow_nan=False)


def test_all_bets_exports_exact_strategy_decisions_without_network(monkeypatch):
    e, p = event(), prediction()
    monkeypatch.setattr(api, "_get_odds", lambda: [e])
    monkeypatch.setattr(api, "_get_prediction_index", lambda: {("A", "B"): p})
    monkeypatch.setattr(api, "_refresh_agent_picks", lambda odds: None)
    monkeypatch.setattr(api, "_maybe_prekickoff_refresh", lambda odds: None)
    monkeypatch.setattr(api, "_get_agent_pick", lambda vb: None)
    row = api.all_bets()["all_bets"][0]
    # The logged policy has to name whatever actually chose the pick.
    assert row["selection_policy"] == "market_favorite_consensus_v1"
    assert row["combined"]["consensus_pick"] == row["combined"]["market_favorite"]
    assert row["prediction"] == p
    assert all(b["pricing_version"] == "settlement_distribution_v1" for b in row["bets"])
    json.dumps(row, allow_nan=False)


def _candidate(vb, market, outcome, team=None):
    return next(b for b in vb["bets"]
                if b["market"] == market and b["outcome"] == outcome
                and (team is None or b.get("team") == team))


def test_model_probability_is_shrunk_toward_the_market_before_pricing():
    """The model is overconfident, so its disagreement is not taken at face value.

    This vanished once already: claude applied the blend in the EV line, codex
    kept it inside the stress-tested selector, and merging the two dropped it
    from both paths. Nothing failed - the site simply started showing EVs
    roughly twice the size and staking to match. Hence this test.
    """
    e, p = event(), prediction()
    vb = api._compute_value_bets(p, [e], "A", "B")
    home = _candidate(vb, "1X2", "home_win", "A")

    raw, shown, market = home["model_probability_raw"], home["probability"], home["market_probability"]
    assert market is not None, "1X2 must carry a market probability to blend against"
    assert raw != market, "test is meaningless unless model and market disagree"
    # Halfway between the two, and strictly inside the interval they span.
    assert shown == pytest.approx(api.MODEL_MARKET_BLEND * raw
                                  + (1 - api.MODEL_MARKET_BLEND) * market, abs=1e-4)
    assert min(raw, market) < shown < max(raw, market)
    # Everything priced off it uses the blended number, not the raw one.
    assert home["expected_value"] == pytest.approx(shown * home["best_odds"] - 1, abs=1e-3)


def test_totals_are_shrunk_harder_than_result_markets():
    """Goal markets earned a stronger pull; the constants must stay distinct."""
    assert api.MODEL_MARKET_BLEND_TOTALS < api.MODEL_MARKET_BLEND
    # A half line settles win/lose with no refund, which is what makes a
    # market probability meaningful here; the shared fixture only carries a
    # quarter line, so this builds its own.
    e = deepcopy(event())
    e["bookmakers"][0]["markets"].append(
        {"key": "totals", "outcomes": [{"name": "Over", "point": 2.5, "price": 1.95},
                                       {"name": "Under", "point": 2.5, "price": 1.95}]})
    vb = api._compute_value_bets(prediction(), [e], "A", "B")
    over = next(b for b in vb["bets"]
                if b["market"].startswith("Over/Under") and b["market_probability"] is not None)
    expected = (api.MODEL_MARKET_BLEND_TOTALS * over["model_probability_raw"]
                + (1 - api.MODEL_MARKET_BLEND_TOTALS) * over["market_probability"])
    assert over["probability"] == pytest.approx(expected, abs=1e-4)


def test_markets_that_can_push_are_left_unblended():
    """A quarter line has refund mass, so a blended win probability would not
    describe any settlement we could actually pay out."""
    vb = api._compute_value_bets(prediction(), [event()], "A", "B")
    for bet in vb["bets"]:
        if bet.get("push_probability"):
            assert bet["market_probability"] is None
            assert bet["probability"] == bet["model_probability_raw"]

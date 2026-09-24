import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.combo_ticket import build_tickets, combo_report, leg_pool, score_ticket


def leg(home, away, prob, odds, market_prob=None, **extra):
    return {"home_team": home, "away_team": away, "commence_time": "2026-09-19T13:30:00Z",
            "sport_key": "soccer_germany_bundesliga", "market": "1X2", "outcome": "home_win",
            "stressed_probability": max(0, prob - .03), "team": home, "best_odds": odds, "bookmaker": "Book", "probability": prob,
            "market_probability": market_prob, "expected_value": prob * odds - 1, **extra}


def vb(home, away, bets, **extra):
    return ({"home_team": home, "away_team": away},
            {"odds_found": True, "snapshot_valid": True, "home_team": home, "away_team": away,
             "sport_key": "soccer_germany_bundesliga", "commence_time": "2026-09-19T13:30:00Z",
             "bets": bets, **extra})


def candidate(prob, odds, **extra):
    base = {"market": "1X2", "outcome": "home_win", "team": "A", "best_odds": odds,
            "probability": prob, "expected_value": prob * odds - 1, "bookmaker": "Book",
            "quote_fresh": True, "market_probability": 1 / odds,
            "payout_distribution": [{"profit": odds-1, "probability": prob}, {"profit": -1, "probability": 1-prob}],
            "selection_market_reference": {"books": {"r1": prob-.04, "r2": prob-.04, "r3": prob-.04}}}
    base.update(extra)
    return base


def test_probabilities_and_odds_multiply():
    t = score_ticket([leg("A", "B", 0.8, 1.5), leg("C", "D", 0.5, 2.0)])
    assert t["combined_odds"] == 3.0
    assert t["probability"] == 0.4
    # 0.4 * 3.0 - 1 = 0.2
    assert abs(t["expected_value"] - 0.2) < 1e-9


def test_stress_haircut_lowers_edge_more_with_more_legs():
    two = score_ticket([leg("A", "B", 0.8, 1.5), leg("C", "D", 0.8, 1.5)])
    three = score_ticket([leg("A", "B", 0.8, 1.5), leg("C", "D", 0.8, 1.5), leg("E", "F", 0.8, 1.5)])
    two_gap = two["probability"] - two["stressed_probability"]
    three_gap = three["probability"] - three["stressed_probability"]
    assert three_gap > two_gap


def test_only_one_leg_per_fixture_is_ever_used():
    """Two bets on the same match are dependent; multiplying them would lie."""
    pool = leg_pool([vb("A", "B", [candidate(0.75, 1.6), candidate(0.70, 1.7, outcome="over")])])
    assert len(pool) == 1


def test_low_probability_and_negative_ev_legs_are_rejected():
    assert leg_pool([vb("A", "B", [candidate(0.40, 3.0)])]) == []          # below floor
    assert leg_pool([vb("A", "B", [candidate(0.60, 1.2)])]) == []          # negative EV
    assert leg_pool([vb("A", "B", [candidate(0.90, 1.8, selection_market_reference={"books": {"r1": .5, "r2": .5, "r3": .5}})])]) == []
    assert leg_pool([vb("A", "B", [candidate(0.70, 1.8, quote_fresh=False)])]) == []


def test_in_play_and_expired_snapshots_are_skipped():
    assert leg_pool([vb("A", "B", [candidate(0.8, 1.6)], in_play=True)]) == []
    assert leg_pool([vb("A", "B", [candidate(0.8, 1.6)], exclusion="expired")]) == []


def test_tickets_need_a_positive_edge_after_stress():
    thin = [leg("A", "B", 0.60, 1.68), leg("C", "D", 0.60, 1.68)]  # EV positive, thin
    assert all(t["stressed_expected_value"] > 0 for t in build_tickets(thin))


def test_ranking_prefers_growth_over_raw_expected_value():
    legs = [leg("A", "B", 0.80, 1.40), leg("C", "D", 0.80, 1.40), leg("E", "F", 0.58, 2.40)]
    tickets = build_tickets(legs)
    assert tickets, "expected at least one qualifying ticket"
    best = tickets[0]
    # A longer ticket can show a bigger EV while being ranked lower.
    assert all(best["ranking_score"] >= t["ranking_score"] for t in tickets)


def test_report_explains_itself_when_nothing_qualifies():
    report = combo_report([vb("A", "B", [candidate(0.40, 3.0)])])
    assert report["recommended"] is None
    assert report["reason"]
    assert report["experimental"] is True


def test_leg_without_enough_independent_bookmakers_is_rejected():
    """The single-bet view excludes these as unverifiable; so must the combo."""
    thin = candidate(0.75, 1.6, selection_market_reference={"book_count": 1, "books": {}})
    assert leg_pool([vb("A", "B", [thin])]) == []
    assert leg_pool([vb("A", "B", [candidate(0.75, 1.6, selection_market_reference=None)])]) == []


def test_market_probability_only_when_every_leg_has_one():
    partial = score_ticket([leg("A", "B", 0.8, 1.5, market_prob=0.65),
                            leg("C", "D", 0.8, 1.5, market_prob=None)])
    assert partial["market_probability"] is None
    assert partial["model_market_gap"] is None


def test_days_are_split_by_local_kickoff_date():
    from src.combo_ticket import match_day
    # Matchdays use the Europe/Berlin date, including late UTC kickoffs.
    assert match_day("2026-09-19T18:30:00Z") == "2026-09-19"
    assert match_day("2026-09-20T13:30:00Z") == "2026-09-20"
    assert match_day("2026-09-19T23:30:00Z") == "2026-09-20"
    assert match_day("2026-09-19T13:30:00") is None
    assert match_day(None) is None
    assert match_day("not-a-time") is None


def test_day_report_keeps_all_in_ticket_separate_from_the_suggestion():
    from src.combo_ticket import day_reports
    same_day = [leg("A", "B", 0.80, 1.45), leg("C", "D", 0.78, 1.50), leg("E", "F", 0.76, 1.55)]
    days = day_reports(same_day)
    assert len(days) == 1
    day = days[0]
    assert day["eligible_legs"] == 3
    # Every eligible leg is on the all-in slip, whatever the suggestion is.
    assert day["all_in"]["leg_count"] == 3
    # The all-in slip must never land more often than a shorter one.
    assert day["all_in"]["probability"] <= day["recommended"]["probability"]


def test_days_are_reported_separately():
    from src.combo_ticket import day_reports
    mixed = [
        {**leg("A", "B", 0.80, 1.45), "commence_time": "2026-09-19T13:30:00Z"},
        {**leg("C", "D", 0.78, 1.50), "commence_time": "2026-09-19T16:30:00Z"},
        {**leg("E", "F", 0.76, 1.55), "commence_time": "2026-09-20T13:30:00Z"},
    ]
    days = day_reports(mixed)
    assert [d["date"] for d in days] == ["2026-09-19", "2026-09-20"]
    # A single-match day cannot form a combination and must say why.
    assert days[1]["recommended"] is None and days[1]["reason"]


@pytest.mark.parametrize("change", [
    {"bookmaker": "Other"},
    {"commence_time": "2026-09-20T13:30:00Z"},
    {"market": "Handicap 0.0"},
    {"market": "Handicap 0.25"},
    {"market": "Over/Under 3.0"},
    {"home_team": "A"},
])
def test_incompatible_legs_cannot_form_a_ticket(change):
    with pytest.raises(ValueError):
        score_ticket([leg("A", "B", .8, 1.5), leg("C", "D", .8, 1.5, **change)])


def test_duplicate_fixture_rows_do_not_create_extra_legs():
    row = vb("A", "B", [candidate(.75, 1.6)])
    assert len(leg_pool([row, row])) == 1
    assert build_tickets(leg_pool([row, row])) == []


def test_each_bookmakers_price_must_pass_its_own_stress_check():
    offered = candidate(.75, 1.6, bookmaker="Good", bookmaker_key="good")
    worse = candidate(.75, 1.3, bookmaker="Bad", bookmaker_key="bad")
    best = {**offered, "bookmaker_offers": [offered, worse]}
    pool = leg_pool([vb("A", "B", [best])])
    assert [l["bookmaker"] for l in pool] == ["Good"]
    assert pool[0]["passes_single_bet_test"]


def test_forged_reference_count_cannot_qualify():
    c = candidate(.75, 1.6, selection_market_reference={"book_count": 10, "books": {}})
    assert leg_pool([vb("A", "B", [c])]) == []


def test_combined_quote_never_uses_mixed_best_prices():
    rows = []
    for home, away, best_book in [("A", "B", "X"), ("C", "D", "Y")]:
        offers = [candidate(.75, 1.65 if b == best_book else 1.60, bookmaker=b, bookmaker_key=b) for b in ("X", "Y")]
        rows.append(vb(home, away, [{**offers[0], "bookmaker_offers": offers}]))
    tickets = build_tickets(leg_pool(rows))
    assert tickets
    for ticket in tickets:
        assert len({l["bookmaker_key"] for l in ticket["legs"]}) == 1
        assert ticket["combined_odds"] == 2.64  # 1.65 * 1.60, never 1.65 squared
        assert ticket["stake_pct"] <= 1
        assert ticket["independence_assumed"]
        assert not ticket["offered_ticket_price_verified"]
        assert "margin_cost" not in ticket


def test_stake_and_ranking_use_stressed_probabilities():
    ticket = score_ticket([leg("A", "B", .8, 1.5, stressed_probability=.70),
                           leg("C", "D", .8, 1.5, stressed_probability=.70)])
    assert ticket["kelly_fraction"] == pytest.approx((.70**2 * 2.25 - 1) / 1.25)
    assert ticket["stressed_probability"] == .49


def test_api_reprices_each_offer_and_excludes_that_book_from_reference(monkeypatch):
    from datetime import datetime, timezone, timedelta
    from api import app as api
    now = datetime.now(timezone.utc)
    predictions, events = {}, []
    for home, away, best_book in [("A", "B", "X"), ("C", "D", "Y")]:
        p = {"home_team": home, "away_team": away, "probability_home_win": .75,
             "probability_draw": .15, "probability_away_win": .10}
        predictions[(home, away)] = p
        books = []
        for name in ("X", "Y", "r1", "r2"):
            price = 1.70 if name == best_book else 1.65 if name in ("X", "Y") else 1.5
            books.append({"key": name, "title": name, "last_update": now.isoformat(), "markets": [
                {"key": "h2h", "outcomes": [{"name": n, "price": q} for n, q in [(home, price), ("Draw", 5), (away, 8)]]}]})
        events.append({"id": home, "home_team": home, "away_team": away,
                       "sport_key": "soccer_germany_bundesliga", "odds_fetched_at": now.isoformat(),
                       "odds_stage": "final", "commence_time": (now+timedelta(minutes=30)).isoformat(), "bookmakers": books})
    monkeypatch.setattr(api, "_get_odds", lambda: events)
    monkeypatch.setattr(api, "_get_prediction_index", lambda: predictions)
    for p in predictions.values():
        priced = api._compute_value_bets(p, events, p["home_team"], p["away_team"], include_offers=True)
        offers = next(b for b in priced["bets"] if b["outcome"] == "home_win")["bookmaker_offers"]
        assert len(offers) == 4
        for offered in offers:
            assert offered["bookmaker_key"] not in offered["selection_market_reference"]["books"]
            assert offered["expected_value"] == pytest.approx(.75*offered["best_odds"]-1)
            assert max(x["profit"] for x in offered["payout_distribution"]) == pytest.approx(offered["best_odds"]-1)
    report = api.combo_ticket()
    ticket = report["recommended"]
    assert ticket is not None
    assert sorted(l["best_odds"] for l in ticket["legs"]) == [1.65, 1.7]
    assert len({l["bookmaker_key"] for l in ticket["legs"]}) == 1
    assert ticket["legs_passing_single_bet_test"] == 2

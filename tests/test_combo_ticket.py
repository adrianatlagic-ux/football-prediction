import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.combo_ticket import build_tickets, combo_report, leg_pool, score_ticket


def leg(home, away, prob, odds, market_prob=None, **extra):
    return {"home_team": home, "away_team": away, "commence_time": "2026-09-19T13:30:00Z",
            "sport_key": "soccer_germany_bundesliga", "market": "1X2", "outcome": "home_win",
            "conservative_probability": min(prob, market_prob if market_prob is not None else prob),
            "market_agrees": True, "team": home, "best_odds": odds, "bookmaker": "Book", "probability": prob,
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


def test_the_market_checked_probability_falls_faster_with_more_legs():
    """Each leg contributes its own gap between our number and the price."""
    two = score_ticket([leg("A", "B", .8, 1.5, .7), leg("C", "D", .8, 1.5, .7)])
    three = score_ticket([leg("A", "B", .8, 1.5, .7), leg("C", "D", .8, 1.5, .7), leg("E", "F", .8, 1.5, .7)])
    assert (three["probability"] - three["conservative_probability"]
            > two["probability"] - two["conservative_probability"])


def test_only_one_leg_per_fixture_is_ever_used():
    """Two bets on the same match are dependent; multiplying them would lie."""
    pool = leg_pool([vb("A", "B", [candidate(0.75, 1.6), candidate(0.70, 1.7, outcome="over")])])
    assert len(pool) == 1


def test_unlikely_legs_and_legs_the_market_disputes_are_rejected():
    """No edge test any more - a leg must be likely, and the price must agree.

    The second half matters more than it looks: sorted by how far the model
    departs from the price, the most confident fifth of past bets did worst
    against the closing line. A leg the market calls the underdog is a worse
    bet for that reason, not a hidden bargain.
    """
    assert leg_pool([vb("A", "B", [candidate(.40, 3.0)])]) == []                      # below the floor
    assert leg_pool([vb("A", "B", [candidate(.90, 1.8, market_probability=.3)])]) == []  # market disagrees
    assert leg_pool([vb("A", "B", [candidate(.90, 1.8, market_probability=None)])]) == []  # no price to check
    # Short odds are fine now: we are not claiming an edge, only a likely outcome.
    assert leg_pool([vb("A", "B", [candidate(.60, 1.2, market_probability=.8)])]) != []


def test_in_play_and_expired_snapshots_are_skipped():
    assert leg_pool([vb("A", "B", [candidate(0.8, 1.6)], in_play=True)]) == []
    assert leg_pool([vb("A", "B", [candidate(0.8, 1.6)], exclusion="expired")]) == []


def test_a_ticket_must_pay_more_than_a_single_bet():
    """Ranking by likelihood alone walks to the shortest prices on the board.

    The first version of this returned a two-fold at 1.58 - worse than simply
    backing one of its own legs. A ticket has to at least double the stake
    before it competes.
    """
    short = [leg("A", "B", .8, 1.2, .75), leg("C", "D", .8, 1.2, .75)]   # 1.44 combined
    assert build_tickets(short) == []
    worthwhile = [leg("A", "B", .7, 1.5, .65), leg("C", "D", .7, 1.5, .65)]  # 2.25
    assert build_tickets(worthwhile)


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


def test_a_stale_quote_is_still_rejected():
    """Freshness is the price check that survived dropping the stress test.

    The reference-bookmaker rule went with it: it excluded every Nations
    League leg, because few books price Andorra or Liechtenstein completely.
    A stale price is different - nobody is offering it any more.
    """
    assert leg_pool([vb("A", "B", [candidate(.75, 1.6, quote_fresh=False)])]) == []
    assert leg_pool([vb("A", "B", [candidate(.75, 1.6, selection_market_reference=None)])]) != []


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


def test_each_bookmaker_is_judged_on_its_own_price():
    """One leg per book, each at that book's own quote - never a mixed price."""
    offered = candidate(.75, 1.6, bookmaker="Good", bookmaker_key="good")
    worse = candidate(.75, 1.3, bookmaker="Bad", bookmaker_key="bad", market_probability=1/1.3)
    best = {**offered, "bookmaker_offers": [offered, worse]}
    pool = {l["bookmaker"]: l for l in leg_pool([vb("A", "B", [best])])}
    assert set(pool) == {"Good", "Bad"}
    assert pool["Good"]["best_odds"] == 1.6 and pool["Bad"]["best_odds"] == 1.3
    assert all(l["market_agrees"] for l in pool.values())


def test_a_leg_the_market_calls_an_underdog_cannot_qualify():
    """However sure the model is - that disagreement predicted worse results."""
    assert leg_pool([vb("A", "B", [candidate(.95, 1.6, market_probability=.35)])]) == []


@pytest.mark.parametrize("warning", ["high_deviation", "contradicts_favorite"])
def test_warning_candidates_can_never_become_combo_legs(warning):
    """The ! warning has the same exclusion meaning in singles and combos."""
    assert leg_pool([vb("A", "B", [candidate(.80, 1.6, market_probability=.70, **{warning: True})])]) == []


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


def test_ranking_and_stake_use_the_market_checked_probability():
    """Stake is flat: sizing by an edge we cannot measure would be a pretence."""
    ticket = score_ticket([leg("A", "B", .8, 1.5, .70), leg("C", "D", .8, 1.5, .70)])
    assert ticket["conservative_probability"] == pytest.approx(.49)
    assert ticket["ranking_score"] == pytest.approx(.49)
    assert "kelly_fraction" not in ticket
    assert ticket["stake_pct"] == pytest.approx(1.0)


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
    assert ticket["legs_the_market_agrees_with"] == 2

from datetime import datetime, timedelta, timezone

from src.price_tip import build_price_tip, match_fixture, model_and_ai_view

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _event(home=1.80, draw=3.80, away=4.50):
    return {"sport_key": "soccer_germany_bundesliga", "home_team": "Bayern Munich",
            "away_team": "Borussia Dortmund", "commence_time": "2026-09-26T13:30:00Z",
            "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Bayern Munich", "price": home}, {"name": "Draw", "price": draw},
                {"name": "Borussia Dortmund", "price": away}]}]}]}


def _book(odds, fetched=NOW - timedelta(minutes=10), **fixture):
    return {"bookmaker": "bet-at-home.de", "fixtures": [{
        "sport_key": "soccer_germany_bundesliga", "home_team": "Bayern München",
        "away_team": "Dortmund", "commence_time": "2026-09-26T13:30:00.000Z",
        "fetched_at": fetched.isoformat(), "odds": odds, **fixture}]}


def test_tip_when_book_pays_above_fair():
    result = build_price_tip(_event(), _book({"home": 1.70, "draw": 3.60, "away": 5.00}), now=NOW)
    tip = result["tip"]
    assert tip["outcome"] == "away_win"
    assert tip["team"] == "Borussia Dortmund"
    # Pinnacle's margin is removed, so the fair odds sit above its quote.
    assert tip["fair_odds"] > tip["pinnacle_odds"]
    assert abs(tip["edge"] - (5.00 * tip["probability"] - 1)) < 1e-3
    assert tip["edge"] >= 0.02


def test_no_tip_below_threshold_but_numbers_still_shown():
    result = build_price_tip(_event(), _book({"home": 1.75, "draw": 3.70, "away": 4.40}), now=NOW)
    assert result["tip"] is None
    assert len(result["outcomes"]) == 3
    assert "pays less" in result["reason"]


def test_no_tip_without_pinnacle():
    event = _event()
    event["bookmakers"] = []
    result = build_price_tip(event, _book({"home": 3.0, "draw": 3.0, "away": 3.0}), now=NOW)
    assert result["tip"] is None and "Pinnacle" in result["reason"]


def test_stale_book_odds_are_refused():
    book = _book({"home": 1.70, "draw": 3.60, "away": 5.00}, fetched=NOW - timedelta(hours=31))
    assert build_price_tip(_event(), book, now=NOW)["tip"] is None


def test_match_needs_kickoff_and_both_teams():
    event = _event()
    assert match_fixture(event, _book({})["fixtures"]) is not None
    assert match_fixture(event, _book({}, commence_time="2026-09-27T13:30:00Z")["fixtures"]) is None
    assert match_fixture(event, _book({}, away_team="Leipzig")["fixtures"]) is None


def test_model_and_ai_view_is_relative_to_the_tip():
    tip = {"market": "1X2", "outcome": "away_win", "probability": 0.21}
    view = model_and_ai_view(tip, {"probability_away_win": 0.25},
                             {"pick": {"market": "1X2", "outcome": "home_win"}})
    assert view["model_agrees"] is True
    assert view["ai_agrees"] is False
    assert model_and_ai_view(None, {}, None)["model_agrees"] is None


def test_spellings_that_share_no_plain_word_still_match():
    event = {**_event(), "home_team": "Bodø/Glimt", "away_team": "Paris Saint Germain"}
    fixtures = _book({}, home_team="Bodo/Glimt", away_team="PSG")["fixtures"]
    assert match_fixture(event, fixtures) is not None


def _full_book(**markets):
    return _book({"home": 1.70, "draw": 3.60, "away": 4.40}, markets=markets,
                 markets_fetched_at=(NOW - timedelta(minutes=10)).isoformat())


def test_double_chance_and_draw_no_bet_come_from_pinnacle_1x2():
    # Pinnacle 1.80/3.80/4.50 -> fair home 53.4%, draw 25.3%, away 21.3%.
    book = _full_book(spreads=[{"point": 0.5, "home": 1.40, "away": 4.0},
                               {"point": 0.0, "home": 1.30, "away": 3.20}], totals=[])
    rows = {(r["market"], r["side"]): r for r in build_price_tip(_event(), book, now=NOW)["outcomes"]}
    fair_h = (1 / 1.80) / (1 / 1.80 + 1 / 3.80 + 1 / 4.50)
    fair_d = (1 / 3.80) / (1 / 1.80 + 1 / 3.80 + 1 / 4.50)
    assert rows[("Handicap +0.5", "home")]["probability"] == round(fair_h + fair_d, 4)
    dnb = rows[("Handicap 0.0", "home")]
    # A draw refunds the stake, so it counts at stake value in the edge.
    assert abs(dnb["edge"] - (1.30 * fair_h + fair_d - 1)) < 1e-3
    # Away -0.5 at home point +0.5 is an away win.
    assert rows[("Handicap -0.5", "away")]["probability"] == round(1 - fair_h - fair_d, 4)


def test_other_lines_only_when_pinnacle_quotes_the_same_line():
    event = _event()
    event["bookmakers"][0]["markets"].append({"key": "totals", "outcomes": [
        {"name": "Over", "price": 1.95, "point": 2.5}, {"name": "Under", "price": 1.95, "point": 2.5}]})
    book = _full_book(totals=[{"point": 2.5, "over": 2.20, "under": 1.70},
                              {"point": 3.5, "over": 3.50, "under": 1.30}],
                      spreads=[{"point": -1.5, "home": 3.0, "away": 1.4}])
    result = build_price_tip(event, book, now=NOW)
    markets = {r["market"] for r in result["outcomes"]}
    assert "Over/Under 2.5" in markets
    assert "Over/Under 3.5" not in markets and "Handicap -1.5" not in markets
    assert result["tip"]["market"] == "Over/Under 2.5" and result["tip"]["outcome"] == "Over"
    assert result["tip"]["edge"] == round(2.20 * 0.5 - 1, 4)


def test_no_tip_when_book_and_pinnacle_were_read_apart():
    event = {**_event(), "odds_fetched_at": (NOW - timedelta(hours=3)).isoformat()}
    result = build_price_tip(event, _book({"home": 1.70, "draw": 3.60, "away": 5.00}), now=NOW)
    assert result["tip"] is None and "different time" in result["reason"]
    assert len(result["outcomes"]) == 3

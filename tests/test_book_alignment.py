from api import app as api


def _setup(monkeypatch, fetched_at):
    fixture = {"home_team": "Croatia", "away_team": "England", "commence_time": "2026-10-03T16:00:00.000Z",
               "fetched_at": fetched_at, "odds": {"home": 3.4, "draw": 3.1, "away": 2.2}}
    monkeypatch.setattr(api.book_odds, "load", lambda: {"fixtures": [fixture]})
    monkeypatch.setattr("src.price_tip.match_fixture", lambda event, fixtures: fixtures[0])


def _event(bookmakers):
    return {"home_team": "Croatia", "away_team": "England", "commence_time": "2026-10-03T16:00:00Z",
            "odds_fetched_at": "2026-10-03T06:13:00+00:00", "bookmakers": bookmakers}


def test_a_later_read_counts_when_the_snapshot_has_no_other_prices(monkeypatch):
    _setup(monkeypatch, "2026-10-03T10:55:00+00:00")
    out = api._with_book_odds(_event([]))
    assert [b["key"] for b in out["bookmakers"]] == [api.USER_BOOK_KEY]


def test_a_later_read_is_not_set_beside_another_bookmakers_price(monkeypatch):
    _setup(monkeypatch, "2026-10-03T10:55:00+00:00")
    pinnacle = {"key": "pinnacle", "markets": []}
    out = api._with_book_odds(_event([pinnacle]))
    assert [b["key"] for b in out["bookmakers"]] == ["pinnacle"]

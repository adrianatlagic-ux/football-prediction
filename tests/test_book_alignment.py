from api import app as api


def _setup(monkeypatch, fetched_at):
    fixture = {"home_team": "Croatia", "away_team": "England", "commence_time": "2026-10-03T16:00:00.000Z",
               "fetched_at": fetched_at, "odds": {"home": 3.4, "draw": 3.1, "away": 2.2}}
    monkeypatch.setattr(api.book_odds, "load", lambda: {"fixtures": [fixture]})
    monkeypatch.setattr("src.price_tip.match_fixture", lambda event, fixtures, events=None: fixtures[0])


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


def test_coverage_says_why_a_price_is_missing(monkeypatch):
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)
    soon = (now + timedelta(minutes=45)).isoformat()
    later = (now + timedelta(hours=5)).isoformat()
    events = [{"id": "w", "sport_key": "nl", "home_team": "Wales", "away_team": "Denmark", "commence_time": soon},
              {"id": "p", "sport_key": "nl", "home_team": "Portugal", "away_team": "Norway", "commence_time": later},
              {"id": "i", "sport_key": "nl", "home_team": "Ireland", "away_team": "Israel", "commence_time": later}]
    fixtures = [
        {"sport_key": "nl", "home_team": "Wales", "away_team": "Denmark", "commence_time": soon,
         "fetched_at": (now - timedelta(hours=12)).isoformat(), "markets": {"totals": [1]}},
        {"sport_key": "nl", "home_team": "Portugal", "away_team": "Norway", "commence_time": later,
         "fetched_at": now.isoformat(), "markets": {}},
    ]
    monkeypatch.setattr(api, "_odds_cache", events)
    monkeypatch.setattr(api, "_final_odds_cache", {})
    monkeypatch.setattr(api.book_odds, "load", lambda: {"fixtures": fixtures})
    rows = {r["match"].split(" - ")[0]: r["status"] for r in api._book_coverage(now)["matches"]}
    assert rows == {"Wales": "stale", "Portugal": "1x2_only", "Ireland": "missing"}

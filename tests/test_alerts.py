from src import alerts, book_odds


def test_an_alert_is_written_once_a_day():
    assert alerts.record("bet-at-home", "cl last_hour", "kaputt") is True
    assert alerts.record("bet-at-home", "cl last_hour", "kaputt") is False
    assert alerts.record("odds-api", "quota", "knapp") is True
    assert [a["source"] for a in alerts.recent()] == ["bet-at-home", "odds-api"]


def test_a_failed_bet_at_home_read_raises_an_alert():
    book_odds._log_refresh("soccer_uefa_champs_league", "last_hour", 9, "failed: no bet-at-home odds in the read")
    book_odds._log_refresh("soccer_germany_bundesliga", "morning", 6, "full book")
    found = alerts.recent()
    assert len(found) == 1 and "Champions League" in found[0]["message"]


def test_trev0n_markets_become_our_book():
    bah = lambda **k: {"bookmaker": "bet-at-home.de", **k}
    item = {"home": "Eintracht Frankfurt", "away": "FC Koln", "date": "2026-10-16T18:30:00.000Z", "markets": [
        {"market": "1X2", "scope": "Full Time", "bookmakers": [bah(home=2, draw=4, away=3.3)]},
        {"market": "Double Chance", "scope": "Full Time", "bookmakers": [bah(**{"1X": 1.28, "12": 1.23, "X2": 1.8})]},
        {"market": "Asian Handicap", "scope": "Full Time", "handicap": "-1.50", "bookmakers": [bah(home=3.3, away=1.28)]},
        {"market": "Asian Handicap", "scope": "Full Time", "handicap": "0.50", "bookmakers": [bah(home=1.35, away=3)]},
        {"market": "Asian Handicap", "scope": "Full Time", "handicap": "-2.25", "bookmakers": []},
        {"market": "Draw No Bet", "scope": "Full Time", "handicap": 0, "bookmakers": [bah(home=1.48, away=2.45)]},
    ]}
    book = book_odds.parse_scraped_markets(item)
    lines = {s["point"]: s for s in book["spreads"]}
    assert lines[-1.5] == {"point": -1.5, "home": 3.3, "away": 1.28}
    assert lines[0.0] == {"point": 0.0, "home": 1.48, "away": 2.45}
    assert lines[0.5]["home"] == 1.35                     # AH +0.5 beats Double Chance 1X 1.28
    assert lines[-0.5]["away"] == 1.8                     # Double Chance X2
    assert book["totals"] == [] and book_odds.has_markets(book)

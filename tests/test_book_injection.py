"""bet-at-home's odds enter the bet table only when read with the snapshot."""
import json
from datetime import datetime, timedelta, timezone

from api import app as api
from src import book_odds
from tests.test_bet_selection import event, prediction


def _renamed(obj):
    # Real team names: the fixture matcher ignores one-letter tokens.
    return json.loads(json.dumps(obj).replace('"A"', '"Aachen"').replace('"B"', '"Bochum"'))


def _write_book(tmp_path, monkeypatch, fetched, markets=True):
    fixture = {"sport_key": "soccer_germany_bundesliga", "home_team": "Aachen", "away_team": "Bochum",
               "commence_time": event()["commence_time"], "fetched_at": fetched.isoformat(),
               "odds": {"home": 2.3, "draw": 3.3, "away": 3.9}}
    if markets:
        fixture.update(markets_fetched_at=fetched.isoformat(), markets={
            "totals": [{"point": 1.5, "over": 1.3, "under": 3.4}],
            "spreads": [{"point": 0.0, "home": 1.7, "away": 2.2}, {"point": -0.5, "home": 2.3, "away": 1.7}],
            "btts": {"yes": 1.9, "no": 1.9}})
    path = tmp_path / "latest.json"
    path.write_text(json.dumps({"bookmaker": "bet-at-home.de", "fixtures": [fixture]}))
    monkeypatch.setenv("BOOK_ODDS_PATH", str(path))


def _snapshot_event():
    return {**_renamed(event()), "odds_fetched_at": datetime.now(timezone.utc).isoformat(), "odds_stage": "final"}


def test_user_book_prices_every_market_it_lists(tmp_path, monkeypatch):
    _write_book(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(minutes=5))
    vb = api._compute_value_bets(_renamed(prediction()), [_snapshot_event()], "Aachen", "Bochum")
    bets = {(b["market"], b["outcome"], b["team"]): b for b in vb["bets"]}
    home = bets[("1X2", "home_win", "Aachen")]
    assert home["bookmaker_key"] == api.USER_BOOK_KEY and home["best_odds"] == 2.3
    # Draw No Bet, both teams to score and a total only bet-at-home quotes.
    assert bets[("Handicap 0.0", "handicap", "Aachen")]["best_odds"] == 1.7
    assert ("BTTS", "Yes", None) in bets
    assert ("Over/Under 1.5", "Over", None) in bets
    # The other book's quarter line stays out, as before.
    assert not any(m.startswith("Over/Under 0.75") for m, _, _ in bets)


def test_book_read_apart_from_the_snapshot_is_left_out(tmp_path, monkeypatch):
    _write_book(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(hours=3))
    vb = api._compute_value_bets(_renamed(prediction()), [_snapshot_event()], "Aachen", "Bochum")
    assert all(b["bookmaker_key"] != api.USER_BOOK_KEY for b in vb["bets"])


def test_window_refresh_respects_the_monthly_budget(tmp_path, monkeypatch):
    _write_book(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(hours=5), markets=False)
    monkeypatch.setenv("APIFY_TOKEN", "x")
    monkeypatch.setattr(book_odds, "MONTHLY_BUDGET", 0.01)
    calls = []
    monkeypatch.setattr(book_odds, "fetch_league",
                        lambda key, items, full_book=False: calls.append((items, full_book)) or [])
    soon = {**event(), "commence_time": (datetime.now(timezone.utc) + timedelta(minutes=40)).isoformat()}
    assert book_odds.refresh_if_due("soccer_germany_bundesliga", [soon])
    assert calls == [(1, False)]
    assert book_odds.spent_this_month() == book_odds.PRICE_PER_MATCH


def test_most_likely_pick_is_the_markets_likeliest_in_the_odds_range():
    e = _snapshot_event()
    e["bookmakers"][0]["markets"] = [
        {"key": "h2h", "outcomes": [{"name": "Aachen", "price": 1.5}, {"name": "Draw", "price": 4.0},
                                    {"name": "Bochum", "price": 6.0}]},
        {"key": "totals", "outcomes": [{"name": "Over", "point": 0.5, "price": 1.05},
                                       {"name": "Under", "point": 0.5, "price": 9.0}]}]
    vb = api._compute_value_bets(_renamed(prediction()), [e], "Aachen", "Bochum")
    pick = vb["likely_pick"]
    # Over 0.5 is likelier but priced at 1.05, below the 1.30 floor.
    assert pick["market"] == "1X2" and pick["team"] == "Aachen"

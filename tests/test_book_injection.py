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
    # Both teams to score and this total are only quoted by bet-at-home.
    assert ("BTTS", "Yes", None) in bets
    assert ("Over/Under 1.5", "Over", None) in bets
    # Refund and split-stake lines are not displayed as binary bets.
    assert ("Handicap 0.0", "handicap", "Aachen") not in bets
    assert not any(m.startswith("Over/Under 0.75") for m, _, _ in bets)


def test_other_bookmakers_handicap_remains_available_when_user_book_omits_the_line(tmp_path, monkeypatch):
    _write_book(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(minutes=5))
    e = _snapshot_event()
    e["bookmakers"][0]["markets"].append({"key": "spreads", "last_update": e["odds_fetched_at"],
        "outcomes": [{"name": "Aachen", "point": 0.5, "price": 1.72},
                     {"name": "Bochum", "point": -0.5, "price": 2.22}]})
    vb = api._compute_value_bets(_renamed(prediction()), [e], "Aachen", "Bochum")
    pick = next(b for b in vb["bets"] if b["market"] == "Handicap +0.5" and b["team"] == "Aachen")
    assert pick["best_odds"] == 1.72
    assert pick["bookmaker_key"] != api.USER_BOOK_KEY


def test_bet_at_home_quote_stays_when_later_fetch_omits_it(tmp_path, monkeypatch):
    from src.odds_schedule import retain_missing_quotes
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=5)
    _write_book(tmp_path, monkeypatch, old_time)
    old = _snapshot_event()
    old["odds_fetched_at"] = old_time.isoformat()
    old = api._with_book_odds(old, [old])
    new = _snapshot_event()
    new["id"] = old["id"]
    new["commence_time"] = old["commence_time"]
    merged = retain_missing_quotes(old, new)
    vb = api._compute_value_bets(_renamed(prediction()), [merged], "Aachen", "Bochum")
    retained = next(b for b in vb["bets"] if b["market"] == "Over/Under 1.5" and b["outcome"] == "Over")
    assert retained["best_odds"] == 1.3
    assert retained["bookmaker_key"] == api.USER_BOOK_KEY
    assert retained["quote_carried_forward"]
    assert retained["quote_last_update"] == old_time.isoformat()


def test_failed_refresh_does_not_relabel_stale_market_quotes(tmp_path, monkeypatch):
    # A stale book must not acquire the current snapshot's timestamp.
    _write_book(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(hours=3))
    vb = api._compute_value_bets(_renamed(prediction()), [_snapshot_event()], "Aachen", "Bochum")
    mine = [b for b in vb["bets"] if b["bookmaker_key"] == api.USER_BOOK_KEY]
    assert not mine


def test_window_refresh_respects_the_monthly_budget(tmp_path, monkeypatch):
    _write_book(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(hours=5), markets=False)
    monkeypatch.setenv("APIFY_TOKEN", "x")
    monkeypatch.setattr(book_odds, "MONTHLY_BUDGET", 0.0)
    calls = []
    monkeypatch.setattr(book_odds, "fetch_league",
                        lambda key, items, full_book=False: calls.append((items, full_book)) or
                        [{"sport_key": "soccer_germany_bundesliga", "home_team": "Aachen", "away_team": "Bochum",
                          "commence_time": "2026-10-14T19:00:00Z", "fetched_at": "x", "odds": {}}])
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


def test_fresh_1x2_does_not_renew_stale_extra_markets(tmp_path, monkeypatch):
    _write_book(tmp_path, monkeypatch, datetime.now(timezone.utc))
    path = book_odds.path()
    stored = json.loads(path.read_text())
    stored['fixtures'][0]['markets_fetched_at'] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    path.write_text(json.dumps(stored))
    vb = api._compute_value_bets(_renamed(prediction()), [_snapshot_event()], 'Aachen', 'Bochum')
    mine = [b for b in vb['bets'] if b['bookmaker_key'] == api.USER_BOOK_KEY]
    assert mine and all(b['market'] == '1X2' for b in mine)


def test_fresh_injected_quote_replaces_carried_quote_from_other_book(tmp_path, monkeypatch):
    from copy import deepcopy
    now = datetime.now(timezone.utc)
    _write_book(tmp_path, monkeypatch, now)
    old = _snapshot_event()
    old_time = (now - timedelta(hours=5)).isoformat()
    old["bookmakers"][0]["markets"].append({
        "key": "totals", "last_update": old_time, "carried_forward": True,
        "outcomes": [{"name": "Over", "point": 1.5, "price": 1.9},
                     {"name": "Over", "point": 3.5, "price": 2.4}]})
    untouched = deepcopy(old)
    merged = api._with_book_odds(old, [old])
    offer = api._best_price(merged, "totals", "Over", 1.5)
    assert offer["price"] == 1.3 and offer["bookmaker_key"] == api.USER_BOOK_KEY
    assert not offer["carried_forward"]
    missing = api._best_price(merged, "totals", "Over", 3.5)
    assert missing["price"] == 2.4 and missing["carried_forward"]
    assert missing["last_update"] == old_time
    assert old == untouched
    # Repeated injection must not reintroduce the superseded price.
    again = api._with_book_odds(merged, [merged])
    assert api._best_price(again, "totals", "Over", 1.5)["price"] == 1.3

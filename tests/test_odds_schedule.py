from datetime import datetime, timezone, timedelta
import pytest
from api import app as api
from src.odds_schedule import stamp_event, snapshot_context


def fixture(now, kickoff=None):
    return {"id": "bl-one", "sport_key": "soccer_germany_bundesliga", "home_team": "A", "away_team": "B",
            "commence_time": (kickoff or now+timedelta(hours=1)).isoformat(),
            "bookmakers": [{"title": "Book", "last_update": now.isoformat(), "markets": [
                {"key": "h2h", "outcomes": [{"name": "A", "price": 2.2}, {"name": "Draw", "price": 3.4}, {"name": "B", "price": 4.0}]}]}]}


def test_final_snapshot_stays_visible_until_kickoff_not_live():
    now = datetime.now(timezone.utc)
    fetched = now-timedelta(minutes=50)
    event = stamp_event(fixture(fetched, now+timedelta(minutes=10)), fetched, "final")
    context = snapshot_context(event, now)
    assert context["snapshot_valid"] and context["quote_basis"] == "scheduled_snapshot_not_live"
    prediction = {"home_team": "A", "away_team": "B", "probability_home_win": .5,
                  "probability_draw": .3, "probability_away_win": .2}
    vb = api._compute_value_bets(prediction, [event], "A", "B")
    assert vb["market_favorite"] is not None
    assert vb["odds_fetched_at"] == fetched.isoformat()
    assert not snapshot_context(event, now+timedelta(minutes=10))["snapshot_valid"]
    # An old provider timestamp is not silently renewed by a new fetch.
    event["bookmakers"][0]["last_update"] = (fetched-timedelta(hours=2)).isoformat()
    assert api._compute_value_bets(prediction, [event], "A", "B")["market_favorite"] is None


def test_initial_snapshot_expires_at_daily_refresh_boundary():
    # Fetched three hours before the 06:00 UTC morning read.
    fetched = datetime(2026, 9, 19, 3, tzinfo=timezone.utc)
    event = stamp_event(fixture(fetched, fetched+timedelta(hours=8)), fetched, "initial")
    assert snapshot_context(event, fetched+timedelta(hours=2))["snapshot_valid"]
    assert not snapshot_context(event, fetched+timedelta(hours=3))["snapshot_valid"]


@pytest.fixture
def clock_and_caches(monkeypatch):
    clock = {"now": datetime(2026, 9, 19, 5, tzinfo=timezone.utc)}
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]
    monkeypatch.setattr(api, "datetime", Clock)
    for name, value in (("_odds_cache", []), ("_odds_cache_date", None),
                        ("_odds_daily_refresh_date", None), ("_odds_cache_fetched_at", 0),
                        ("_final_odds_cache", {}), ("_final_odds_attempts", {}),
                        ("ODDS_CACHE_TTL_SECONDS", 0)):
        monkeypatch.setattr(api, name, value)
    return clock


def test_initial_daily_final_fetch_once_at_first_request(monkeypatch, clock_and_caches):
    clock = clock_and_caches
    kickoff = clock["now"].replace(hour=17)
    calls = []
    def daily():
        calls.append("daily")
        return [fixture(clock["now"], kickoff)]
    def final(sport, events):
        calls.append(sport)
        return [fixture(clock["now"], kickoff)]
    monkeypatch.setattr(api, "_fetch_odds", daily)
    monkeypatch.setattr(api, "_fetch_league_odds", final)
    assert api._get_odds()[0]["odds_stage"] == "initial"
    clock["now"] += timedelta(minutes=20)
    api._get_odds()
    assert len(calls) == 1
    clock["now"] = clock["now"].replace(hour=6, minute=5)
    assert api._get_odds()[0]["odds_stage"] == "daily"
    clock["now"] = clock["now"].replace(hour=16, minute=5)
    final_snapshot = api._get_odds()[0]
    assert final_snapshot["odds_stage"] == "final"
    clock["now"] += timedelta(minutes=40)
    assert api._get_odds()[0] == final_snapshot
    assert calls == ["daily", "daily", "soccer_germany_bundesliga"]


def test_failed_final_never_relabels_old_quote_or_retries_every_view(monkeypatch, clock_and_caches):
    clock = clock_and_caches
    clock["now"] = clock["now"].replace(hour=16, minute=5)
    monkeypatch.setattr(api, "_fetch_odds", lambda: [fixture(clock["now"], clock["now"].replace(hour=17))])
    calls = []
    def fail(sport, events):
        calls.append(events)
        raise OSError("provider unavailable")
    monkeypatch.setattr(api, "_fetch_league_odds", fail)
    first = api._get_odds()[0]
    assert first["odds_stage"] == "daily" and first["final_refresh_status"] == "pending_or_failed"
    api._get_odds()
    assert len(calls) == 1


def test_final_refresh_keeps_a_selection_missing_from_the_new_response(monkeypatch, clock_and_caches):
    from copy import deepcopy
    clock = clock_and_caches
    clock['now'] = clock['now'].replace(hour=16, minute=5)
    earlier = fixture(clock['now'], clock['now'].replace(hour=17))
    earlier['bookmakers'][0]['markets'].append({'key': 'totals', 'outcomes': [
        {'name': 'Over', 'point': 2.5, 'price': 1.9}]})
    final = deepcopy(earlier)
    final['bookmakers'][0]['markets'].pop()
    monkeypatch.setattr(api, '_fetch_odds', lambda: [deepcopy(earlier)])
    monkeypatch.setattr(api, '_fetch_league_odds', lambda sport, events: [deepcopy(final)])
    out = api._get_odds()[0]
    offer = api._best_price(out, 'totals', 'Over', point=2.5)
    assert out['odds_stage'] == 'final'
    assert offer['price'] == 1.9 and offer['carried_forward']


@pytest.mark.parametrize("sport", ["soccer_germany_bundesliga", "soccer_uefa_nations_league"])
def test_event_refresh_uses_its_own_competition_path(monkeypatch, sport):
    import json
    from io import BytesIO
    e = fixture(datetime.now(timezone.utc))
    e["sport_key"] = sport
    seen = []
    def open_(request, timeout):
        seen.append(request.full_url)
        return BytesIO(json.dumps(e).encode())
    monkeypatch.setattr(api.urllib.request, "urlopen", open_)
    monkeypatch.setattr(api, "ODDS_API_KEY", "test-placeholder")
    assert api._fetch_event_odds(e) == e
    assert f"/{sport}/events/bl-one/odds" in seen[0]


def test_daily_fetch_includes_nations_league_quotes(monkeypatch):
    import json
    from io import BytesIO
    from urllib.parse import urlparse
    now = datetime.now(timezone.utc)
    event = {**fixture(now), "sport_key": "soccer_uefa_nations_league",
             "home_team": "Austria", "away_team": "Israel"}
    requested = []

    def open_(request, timeout):
        path = urlparse(request.full_url).path
        requested.append(path)
        data = [event] if path == "/v4/sports/soccer_uefa_nations_league/events" else []
        return BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(api.urllib.request, "urlopen", open_)
    monkeypatch.setattr(api, "ODDS_API_KEY", "test-placeholder")
    events = api._fetch_odds()
    assert api._find_odds_match(events, "Austria", "Israel") == event
    # Three free event lists, plus main-market prices where there are games.
    assert len(requested) == 4
    assert requested[-1] == "/v4/sports/soccer_uefa_nations_league/odds"


def test_audit_reports_daily_and_final_separately(tmp_path, monkeypatch):
    import json
    from scripts.audit_club_bets import main
    now = datetime.now(timezone.utc)
    e = fixture(now)
    def logged(stage, odds, at):
        bet = {"market": "1X2", "outcome": "home_win", "team": "A", "best_odds": odds}
        return {**e, "odds_stage": stage, "logged_at": at.isoformat(), "combined": {"consensus_pick": bet}, "bets": [bet]}
    entries = [logged("daily", 2.5, now-timedelta(hours=2)), logged("final", 2.0, now)]
    result = {**e, "home_score": 1, "away_score": 0, "completed": True, "score_scope": "regulation",
              "observed_at": (now+timedelta(hours=4)).isoformat()}
    logs, results, out = (tmp_path/n for n in ("logs.jsonl", "results.jsonl", "out.json"))
    logs.write_text("\n".join(json.dumps(x) for x in entries))
    results.write_text(json.dumps(result))
    monkeypatch.setattr("sys.argv", ["audit", "--logs", str(logs), "--results", str(results), "--out", str(out)])
    main()
    report = json.loads(out.read_text())
    profit = lambda r: next(g["profit_units"] for g in r["groups"] if g["role"] == "displayed_tip")
    assert profit(report) == 1
    assert profit(report["by_odds_stage"]["daily"]) == 1.5
    assert profit(report["by_odds_stage"]["final"]) == 1


def test_final_batches_matches_and_retries_only_missing(monkeypatch, clock_and_caches):
    clock = clock_and_caches
    clock['now'] = clock['now'].replace(hour=16, minute=5)
    first = fixture(clock['now'], clock['now'].replace(hour=17))
    second = {**first, 'id': 'bl-two', 'home_team': 'C', 'away_team': 'D'}
    later = {**first, 'id': 'bl-later', 'commence_time': clock['now'].replace(hour=20).isoformat()}
    monkeypatch.setattr(api, '_fetch_odds', lambda: [first, second, later])
    calls = []
    def fetch(sport, events):
        calls.append([e['id'] for e in events])
        return [first] if len(calls) == 1 else [second]
    monkeypatch.setattr(api, '_fetch_league_odds', fetch)
    wall = [10000]
    monkeypatch.setattr(api.time, 'time', lambda: wall[0])
    out = api._get_odds()
    assert calls == [['bl-one', 'bl-two']]
    assert out[0]['odds_stage'] == 'final'
    assert out[1]['final_refresh_status'] == 'pending_or_failed'
    assert out[2]['odds_stage'] == 'daily'
    api._get_odds()
    assert len(calls) == 1
    wall[0] += 901
    out = api._get_odds()
    assert calls[-1] == ['bl-two']
    assert out[1]['odds_stage'] == 'final'


def test_league_response_checks_identity_and_requests_three_markets(monkeypatch):
    import json
    from io import BytesIO
    from urllib.parse import urlparse, parse_qs
    now = datetime.now(timezone.utc)
    event = fixture(now)
    wrong = {**event, 'home_team': 'Wrong'}
    empty = {**event, 'id': 'empty', 'bookmakers': []}
    seen = []
    def open_(request, timeout):
        seen.append(request.full_url)
        return BytesIO(json.dumps([wrong, empty, event]).encode())
    monkeypatch.setattr(api.urllib.request, 'urlopen', open_)
    monkeypatch.setattr(api, 'ODDS_API_KEY', 'test-placeholder')
    assert api._fetch_league_odds(event['sport_key'], [event, empty]) == [event]
    query = parse_qs(urlparse(seen[0]).query)
    assert query['markets'] == ['h2h,totals,spreads']
    assert '/events/' not in seen[0]
    assert query['commenceTimeFrom'][0] < query['commenceTimeTo'][0]


def test_morning_prices_request_all_main_markets(monkeypatch):
    import json
    from io import BytesIO
    from urllib.parse import urlparse, parse_qs
    event = fixture(datetime.now(timezone.utc))
    listed = [{**event, 'bookmakers': []}]
    seen = []
    def open_(request, timeout):
        seen.append(parse_qs(urlparse(request.full_url).query))
        return BytesIO(json.dumps([event]).encode())
    monkeypatch.setattr(api.urllib.request, 'urlopen', open_)
    api._add_morning_prices(event['sport_key'], listed, '')
    assert seen[0]['markets'] == ['h2h,totals,spreads']
    assert listed[0]['bookmakers'] == event['bookmakers']

"""bet-at-home's 1X2 odds from OddsPortal, fetched and stored per competition.

The Odds API carries Pinnacle but none of the German-licensed bookmakers;
OddsPortal carries them when read through a German proxy, and carries no
Pinnacle. The price tip needs both at nearly the same moment: a slow
bookmaker's gap to Pinnacle opens in the last hour, when Pinnacle moves and
the bookmaker has not yet followed, and comparing a fresh Pinnacle price with
a bet-at-home quote from the morning would invent gaps that never existed.

So the app refreshes these odds itself inside the same pre-kickoff window
that refreshes Pinnacle. That refresh reads bet-at-home's full market book
(Asian Handicap, Over/Under, Draw No Bet, Double Chance, both teams to
score), which costs 2.3 cents per match instead of 0.3, so it runs once per
match and stops at a monthly budget; past the budget it falls back to 1X2.
(Since 14 October trev0n's scraper, 0.1 cent a match with or without the
markets; see ACTOR.)

OddsPortal cannot be asked for one match, only for a league page, soonest
match first - games already in play included. A refresh therefore pays for
every match from the top of the list down to the last one in the window.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src import apify_budget
from src.foreign_team_names import to_english

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "book_odds" / "latest.json"
# Since 14 October trev0n's scraper: OddsPortal moved to a new site with a
# bot check on 12/13 October, and piotrv1001's scraper has brought no market
# since (only 1X2). trev0n's still reads bet-at-home's 1X2, Asian Handicap,
# Double Chance and Draw No Bet; Over/Under and BTTS are blocked for it too,
# so those come from the Odds API's other bookmakers. 0.1 cent a match.
ACTOR = "trev0n~oddsportal-com-scraper"
SCRAPED_MARKETS = ["Asian Handicap", "Double Chance", "Draw No Bet"]
BOOKMAKER = "bet-at-home.de"
LEAGUES = {
    "soccer_uefa_champs_league": "https://www.oddsportal.com/football/europe/champions-league/",
    "soccer_germany_bundesliga": "https://www.oddsportal.com/football/germany/bundesliga/",
    "soccer_uefa_nations_league": "https://www.oddsportal.com/football/europe/uefa-nations-league/",
}
PRICE_PER_MATCH = 0.001          # USD per match, trev0n's flat price
PRICE_PER_FULL_BOOK = 0.001      # the same: 1X2 always comes with the markets
# Two full reads per match: the morning one and the last-hour one. 7 $ ran
# out on 13 October (duplicate last-hour reads early in the month), and every
# read fell back to 1X2; raised to 20 $. The Apify account limit stays the
# outer guard (src/apify_budget.py).
MONTHLY_BUDGET = float(os.getenv("BOOK_MARKETS_BUDGET_USD", "20.0"))
# A Nations League evening lists ten matches at one kickoff plus those still
# in play; a smaller cap left matches without a book and re-fetched them.
MAX_WINDOW_ITEMS = 20

_lock = threading.Lock()
# One window refresh at a time: every match thread in the window calls in,
# and only the first may pay for a fetch.
_refresh_lock = threading.Lock()


def path() -> Path:
    return Path(os.getenv("BOOK_ODDS_PATH", str(DEFAULT_PATH)))


def spend_path() -> Path:
    return path().with_name("spend.json")


_cache = {"key": None, "data": None}


def load() -> dict:
    """The stored odds, re-read only when the file changed: the bet table and
    the combo ask for them once per match, hundreds of times per request."""
    try:
        stat = path().stat()
        key = (str(path()), stat.st_mtime_ns, stat.st_size)
        if _cache["key"] != key:
            _cache["data"] = json.loads(path().read_text(encoding="utf-8"))
            _cache["key"] = key
        return _cache["data"]
    except (OSError, ValueError):
        return {"bookmaker": BOOKMAKER, "fixtures": [], "fetched_at": {}}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pair(offer: dict, keys: tuple) -> Optional[dict]:
    odds = (offer or {}).get("closingOdds") or {}
    try:
        values = {k: float(odds[k]) for k in keys}
    except (KeyError, TypeError, ValueError):
        return None
    return values if all(v > 1 for v in values.values()) else None


def parse_markets(item: dict) -> dict:
    """bet-at-home's full-time markets from one OddsPortal match.

    OddsPortal's Asian Handicap line is the home side's handicap. Double
    Chance 1X and X2 are the same bets as Asian Handicap +0.5 for home or
    away, so they are merged into that line at whichever price is higher;
    Draw No Bet is Asian Handicap 0. "12" has no handicap form and is left out.
    """
    totals, spreads, btts, dc = {}, {}, None, None
    for market in item.get("markets") or []:
        if market.get("scope") != "Full Time":
            continue
        offer = next((b for b in market.get("bookmakers", []) if b.get("bookmaker") == BOOKMAKER), None)
        if offer is None:
            continue
        kind, line = market.get("market"), market.get("handicap")
        if kind == "Over/Under" and line is not None:
            pair = _pair(offer, ("over", "under"))
            if pair:
                totals[float(line)] = pair
        elif kind == "Asian Handicap" and line is not None:
            pair = _pair(offer, ("home", "away"))
            if pair:
                spreads[float(line)] = pair
        elif kind == "Draw No Bet":
            pair = _pair(offer, ("home", "away"))
            if pair:
                spreads[0.0] = pair
        elif kind == "Both Teams to Score":
            btts = _pair(offer, ("yes", "no"))
        elif kind == "Double Chance":
            dc = _pair(offer, ("homeOrDraw", "drawOrAway"))
    if dc:
        # Home +0.5 is 1X; away +0.5 (home -0.5) is X2.
        plus = spreads.setdefault(0.5, {})
        plus["home"] = max(plus.get("home", 0), dc["homeOrDraw"])
        minus = spreads.setdefault(-0.5, {})
        minus["away"] = max(minus.get("away", 0), dc["drawOrAway"])
    return {"totals": [{"point": k, **v} for k, v in sorted(totals.items())],
            "spreads": [{"point": k, **v} for k, v in sorted(spreads.items())],
            "btts": btts}


def parse_scraped_markets(item: dict) -> dict:
    """bet-at-home's full-time markets from one match of trev0n's scraper.

    The Asian Handicap line is the home side's handicap. Double Chance 1X and
    X2 are Asian Handicap +0.5 home / away and are merged into that line at
    the higher price; Draw No Bet is Asian Handicap 0.
    """
    spreads, dc = {}, None
    for market in item.get("markets") or []:
        if market.get("scope") != "Full Time":
            continue
        offer = next((b for b in market.get("bookmakers", []) if b.get("bookmaker") == BOOKMAKER), None)
        if offer is None:
            continue
        kind = market.get("market")
        try:
            if kind == "Asian Handicap":
                pair = {k: float(offer[k]) for k in ("home", "away")}
                spreads[float(market.get("handicap"))] = pair
            elif kind == "Draw No Bet":
                spreads[0.0] = {k: float(offer[k]) for k in ("home", "away")}
            elif kind == "Double Chance":
                dc = {"homeOrDraw": float(offer["1X"]), "drawOrAway": float(offer["X2"])}
        except (KeyError, TypeError, ValueError):
            continue
    spreads = {k: v for k, v in spreads.items() if all(x > 1 for x in v.values())}
    if dc and all(x > 1 for x in dc.values()):
        plus = spreads.setdefault(0.5, {})
        plus["home"] = max(plus.get("home", 0), dc["homeOrDraw"])
        minus = spreads.setdefault(-0.5, {})
        minus["away"] = max(minus.get("away", 0), dc["drawOrAway"])
    return {"totals": [], "spreads": [{"point": k, **v} for k, v in sorted(spreads.items())], "btts": None}


def fetch_league(sport_key: str, max_items: int, token: Optional[str] = None,
                 full_book: bool = False) -> list:
    """One OddsPortal read of a competition; returns bet-at-home fixtures.

    bet-at-home's own 1X2 price only comes with the per-bookmaker markets, so
    every read asks for them; without `full_book` only the quickest market.
    """
    token = token or os.environ["APIFY_TOKEN"]
    payload = {"leagueUrls": [{"url": LEAGUES[sport_key]}], "fullOdds": True,
               "markets": SCRAPED_MARKETS if full_book else ["Draw No Bet"],
               "marketScope": "Full Time", "includeOpeningOdds": False, "includeFinished": False,
               "maxMatches": max_items, "detailConcurrency": 5, "oddsFormat": "Decimal",
               # The proxy country decides which bookmakers OddsPortal lists;
               # Germany returns exactly the ones licensed there. Datacenter
               # proxies are blocked by the bot check.
               "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"],
                                      "apifyProxyCountry": "DE"}}
    request = urllib.request.Request(
        f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items?token={token}&memory=1024",
        method="POST", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=330) as response:
        items = json.loads(response.read().decode())
    stamp = _now().isoformat()
    out = []
    for m in items:
        if not m.get("home") or not m.get("date"):
            continue
        main = next((mk for mk in m.get("markets") or [] if mk.get("market") == "1X2"), {})
        offer = next((b for b in main.get("bookmakers", []) if b.get("bookmaker") == BOOKMAKER), None)
        try:
            odds = {k: float(offer[k]) for k in ("home", "draw", "away")}
        except (KeyError, TypeError, ValueError):
            continue
        # OddsPortal may answer in another language (it once sent Polish).
        fixture = {"sport_key": sport_key, "home_team": to_english(m["home"]),
                   "away_team": to_english(m["away"]), "commence_time": m["date"],
                   "fetched_at": stamp, "odds": odds}
        if full_book:
            fixture["markets"] = parse_scraped_markets(m)
        out.append(fixture)
    return out


def _identity(f: dict) -> tuple:
    # Names in English, so a newer read replaces an older one stored with
    # the foreign names OddsPortal sometimes sends.
    return (f.get("sport_key"), to_english(f.get("home_team") or ""), to_english(f.get("away_team") or ""),
            str(f.get("commence_time"))[:10])


def store(sport_key: str, fixtures: list, replace: bool = False) -> None:
    """Save fetched fixtures.

    A full read (the script) replaces the competition's list. A window
    refresh only covers the next few matches, so it updates those and keeps
    the rest; a fixture keeps its full market book until a newer fetch of
    the same match brings one.
    """
    with _lock:
        data = dict(load())
        kept = [f for f in data.get("fixtures", []) if f.get("sport_key") != sport_key]
        mine = {} if replace else {_identity(f): f for f in data.get("fixtures", [])
                                   if f.get("sport_key") == sport_key}
        for f in fixtures:
            old = mine.get(_identity(f))
            keeps_old = old and "markets" in old and (
                "markets" not in f or (not has_markets(f["markets"]) and has_markets(old["markets"])))
            if keeps_old:
                # A read without markets, or with empty ones, never replaces a
                # book that had them: the last good markets stay, with their
                # own read time.
                f = {**f, "markets": old["markets"], "markets_fetched_at": old.get("markets_fetched_at")}
            elif "markets" in f:
                f = {**f, "markets_fetched_at": f["fetched_at"]}
            mine[_identity(f)] = f
        data["fixtures"] = kept + list(mine.values())
        stamps = data.get("fetched_at") if isinstance(data.get("fetched_at"), dict) else {}
        stamps[sport_key] = _now().isoformat()
        data["fetched_at"] = stamps
        data["bookmaker"] = BOOKMAKER
        path().parent.mkdir(parents=True, exist_ok=True)
        path().write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _month() -> str:
    return _now().strftime("%Y-%m")


def spent_this_month() -> float:
    try:
        return float(json.loads(spend_path().read_text()).get(_month(), 0.0))
    except (OSError, ValueError, AttributeError):
        return 0.0


def _record_spend(usd: float) -> None:
    try:
        data = json.loads(spend_path().read_text())
    except (OSError, ValueError):
        data = {}
    data[_month()] = round(float(data.get(_month(), 0.0)) + usd, 4)
    spend_path().parent.mkdir(parents=True, exist_ok=True)
    spend_path().write_text(json.dumps(data, indent=1) + "\n")


def has_markets(markets) -> bool:
    """Whether a parsed book holds any extra market at all."""
    return bool(markets) and bool(markets.get("totals") or markets.get("spreads") or markets.get("btts"))


def _strip_markets(fetched: list) -> list:
    return [{k: v for k, v in f.items() if k != "markets"} for f in fetched]


def _has_fresh_book(fixtures: list, event: dict) -> bool:
    """Whether this match already has a full book fetched inside its window.

    An empty book ({}) is the deliberate 1X2-only read past the budget and
    counts; a read whose markets all came back empty does not.
    """
    from src.price_tip import match_fixture
    fixture = match_fixture(event, fixtures)
    if not fixture or not fixture.get("markets_fetched_at"):
        return False
    if fixture.get("markets") != {} and not has_markets(fixture.get("markets")):
        return False
    try:
        kickoff = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
        fetched = datetime.fromisoformat(fixture["markets_fetched_at"])
    except (KeyError, ValueError):
        return False
    return kickoff - fetched <= WINDOW


# Last-hour reads per competition: at most one per LAST_HOUR_COOLDOWN.
LAST_HOUR_COOLDOWN = timedelta(minutes=20)
_last_hour_read_at: dict = {}
# (competition, day) pairs whose last-hour read already came back without
# extra markets once: they get one retry, not one per tick.
_empty_last_hour_days: dict = {}
EMPTY_LAST_HOUR_READS = 2


# The pre-kickoff window a full book belongs to (the app's window is one hour;
# a little slack so a fetch at T-65 min still counts).
WINDOW = timedelta(minutes=75)


# What the last reads did, per competition - shown in /jobs/status so a
# missing price says why (budget, failure) instead of failing silently.
REFRESH_LOG: dict = {}
# Every read, kept on the Fly volume (data/logs is linked there), so a missing
# price can be traced after a restart (bugs/2026-10-13-betathome-nur-siegquoten.md).
REFRESH_LOG_PATH = ROOT / "data" / "logs" / "book_refresh_log.jsonl"


_SPORT_NAMES = {"soccer_uefa_champs_league": "Champions League", "soccer_germany_bundesliga": "Bundesliga",
                "soccer_uefa_nations_league": "Nations League"}


def _log_refresh(sport_key: str, kind: str, items: int, outcome: str) -> None:
    entry = {"at": _now().isoformat(), "kind": kind, "items": items, "outcome": outcome}
    REFRESH_LOG[sport_key] = entry
    if outcome.startswith(("failed", "skipped")):
        from src import alerts
        when = "Morgenabruf" if kind.startswith("morning") else "Abruf vor Anpfiff"
        alerts.record("bet-at-home", f"{sport_key} {kind}",
                      f"bet-at-home ({_SPORT_NAMES.get(sport_key, sport_key)}, {when}): {outcome}")
    try:
        REFRESH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REFRESH_LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"sport_key": sport_key, **entry,
                                     "spent_this_month": round(spent_this_month(), 3)}) + "\n")
    except OSError:
        pass


def load_refresh_log() -> None:
    """The latest read per competition from the file, after a restart."""
    try:
        for line in REFRESH_LOG_PATH.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            REFRESH_LOG[e.pop("sport_key")] = {k: e[k] for k in ("at", "kind", "items", "outcome") if k in e}
    except (OSError, ValueError, KeyError):
        pass


def refresh_if_due(sport_key: str, events: list) -> bool:
    """Fetch the full market book when a match in the window lacks one.

    `events` are the Odds API events of this competition. The fetch size is
    every match from now back to two hours ago (still in play, and so still
    at the top of OddsPortal's list) up to the end of the window. Each match
    is fetched once; past the monthly budget only 1X2 is read. Failures are
    swallowed: without fresh odds the tip simply says so.
    """
    if sport_key not in LEAGUES or not os.getenv("APIFY_TOKEN"):
        return False
    now = _now()
    listed, due = [], []
    for e in events:
        try:
            kickoff = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if now - timedelta(hours=2) <= kickoff <= now + WINDOW:
            listed.append(e)
            if kickoff > now:
                due.append(e)
    with _refresh_lock:
        fixtures = load().get("fixtures", [])
        if not due or all(_has_fresh_book(fixtures, e) for e in due):
            return False
        # One read per competition per cooldown, whatever it brought back: a
        # match whose name never matched kept every later page request paying
        # for a new read (nine reads in two minutes on 6 October).
        last = _last_hour_read_at.get(sport_key)
        if last and now - last < LAST_HOUR_COOLDOWN:
            return False
        if _empty_last_hour_days.get((sport_key, now.date().isoformat()), 0) >= EMPTY_LAST_HOUR_READS:
            return False
        _last_hour_read_at[sport_key] = now
        items = min(len(listed), MAX_WINDOW_ITEMS)
        full = (spent_this_month() + items * PRICE_PER_FULL_BOOK <= MONTHLY_BUDGET
                and apify_budget.allows(items * PRICE_PER_FULL_BOOK))
        if not full and not apify_budget.allows(items * PRICE_PER_MATCH):
            _log_refresh(sport_key, "last_hour", items, "skipped: Apify budget")
            return False
        try:
            fetched = fetch_league(sport_key, items, full_book=full)
        except Exception as exc:
            _log_refresh(sport_key, "last_hour", items, f"failed: {type(exc).__name__}: {exc}"[:200])
            return False
        _record_spend(items * (PRICE_PER_FULL_BOOK if full else PRICE_PER_MATCH))
        apify_budget.note_spend(items * (PRICE_PER_FULL_BOOK if full else PRICE_PER_MATCH))
        if not fetched:
            _log_refresh(sport_key, "last_hour", items, "failed: no bet-at-home odds in the read")
            return False
        if full and fetched and not any(has_markets(f.get("markets")) for f in fetched):
            # OddsPortal served the matches without a single extra market (13
            # October): keep the 1X2 prices. One more try per competition and
            # day after the cooldown; after that the last good markets stay.
            day = (sport_key, now.date().isoformat())
            _empty_last_hour_days[day] = _empty_last_hour_days.get(day, 0) + 1
            retry = _empty_last_hour_days[day] < EMPTY_LAST_HOUR_READS
            _log_refresh(sport_key, "last_hour", items, "failed: no extra markets in the read"
                         + (", one retry in 20 min" if retry else ", no retry today"))
            store(sport_key, _strip_markets(fetched) if retry else [{**f, "markets": {}} for f in fetched])
            return False
        _log_refresh(sport_key, "last_hour", items, "full book" if full else "1X2 only: Apify budget")
        if not full:
            # Past the budget: mark the 1X2 read so the window is not retried.
            fetched = [{**f, "markets": {}} for f in fetched]
        store(sport_key, fetched)
        return True


# How far ahead the daily 1X2 read looks, and how far past the budget it may
# go: at 0.3 cents a match it is the cheap part, and without it neither the
# bet table nor the combo has bet-at-home prices outside the last hour.
DAILY_HORIZON = timedelta(hours=30)
DAILY_RESERVE = 1.0


# A morning read that comes back without a single bet-at-home price (OddsPortal
# served the list without odds on 10 October) is tried again once.
MORNING_RETRY_AFTER = timedelta(minutes=30)
MORNING_RETRIES = 1
_morning_retry: dict = {}


def morning_retries_due(now: Optional[datetime] = None) -> list:
    """Competitions whose empty morning read is due another try; each is
    handed out once per try."""
    now = now or _now()
    due = []
    for sport_key, entry in _morning_retry.items():
        if entry.get("next_at") and entry["next_at"] <= now:
            entry["next_at"] = None
            due.append(sport_key)
    return due


def morning_read_finished(sport_key: str, snapshot_at: str) -> bool:
    """Wait for the supplementary read (including a scheduled empty-read retry).

    If the scraper is disabled, the Odds API alone supplies the candidates.
    A terminal scraper failure also releases this gate; market coverage is
    checked separately before sending anything to Gemini.
    """
    if sport_key not in LEAGUES or not os.getenv("APIFY_TOKEN"):
        return True
    if sport_key in _morning_retry:
        return False
    report = REFRESH_LOG.get(sport_key) or {}
    try:
        completed = datetime.fromisoformat(report["at"].replace("Z", "+00:00"))
        snapshot = datetime.fromisoformat(snapshot_at.replace("Z", "+00:00"))
        return report.get("kind", "").startswith("morning") and completed >= snapshot
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def daily_refresh(sport_key: str, events: list, retry: bool = False) -> bool:
    """The morning read: bet-at-home's full market book for every match in
    the next DAILY_HORIZON, so the bet table and the combo have every market
    all day. Past the budget it falls back to 1X2. `retry` marks a repeat of
    an empty morning read (morning_retries_due)."""
    if sport_key not in LEAGUES or not os.getenv("APIFY_TOKEN"):
        return False
    now = _now()
    listed = 0
    for e in events:
        try:
            kickoff = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        listed += now - timedelta(hours=2) <= kickoff <= now + DAILY_HORIZON
    if not listed:
        return False
    items = min(listed, 40)
    full = (spent_this_month() + items * PRICE_PER_FULL_BOOK <= MONTHLY_BUDGET
            and apify_budget.allows(items * PRICE_PER_FULL_BOOK))
    if not full and (spent_this_month() + items * PRICE_PER_MATCH > MONTHLY_BUDGET + DAILY_RESERVE
                     or not apify_budget.allows(items * PRICE_PER_MATCH)):
        _morning_retry.pop(sport_key, None)
        _log_refresh(sport_key, "morning", items, "skipped: Apify budget")
        return False
    with _refresh_lock:
        try:
            fetched = fetch_league(sport_key, items, full_book=full)
        except Exception as exc:
            _morning_retry.pop(sport_key, None)
            _log_refresh(sport_key, "morning", items, f"failed: {type(exc).__name__}: {exc}"[:200])
            return False
        _record_spend(items * (PRICE_PER_FULL_BOOK if full else PRICE_PER_MATCH))
        apify_budget.note_spend(items * (PRICE_PER_FULL_BOOK if full else PRICE_PER_MATCH))
        no_markets = full and fetched and not any(has_markets(f.get("markets")) for f in fetched)
        if no_markets:
            # The prices came, the extra markets did not (13 October): keep
            # the 1X2 prices and try the full read again.
            store(sport_key, _strip_markets(fetched))
        if not fetched or no_markets:
            attempts = (_morning_retry.get(sport_key, {}).get("attempts", 0) if retry else 0) + 1
            if attempts <= MORNING_RETRIES:
                _morning_retry[sport_key] = {"attempts": attempts, "next_at": now + MORNING_RETRY_AFTER}
                what = "no extra markets" if no_markets else "no bet-at-home odds"
                _log_refresh(sport_key, "morning", items, f"failed: {what} in the read, "
                                                          f"retry {attempts} of {MORNING_RETRIES} in 30 min")
            else:
                _morning_retry.pop(sport_key, None)
                _log_refresh(sport_key, "morning", items, "failed: nothing usable in the read, no retry left")
            return False
        _morning_retry.pop(sport_key, None)
        store(sport_key, fetched)
        _log_refresh(sport_key, "morning" if not retry else "morning retry", items,
                     "full book" if full else "1X2 only: Apify budget")
        return True

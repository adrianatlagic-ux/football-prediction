"""bet-at-home's 1X2 odds from OddsPortal, fetched and stored per competition.

The Odds API carries Pinnacle but none of the German-licensed bookmakers;
OddsPortal carries them when read through a German proxy, and carries no
Pinnacle. The price tip needs both at nearly the same moment: a slow
bookmaker's gap to Pinnacle opens in the last hour, when Pinnacle moves and
the bookmaker has not yet followed, and comparing a fresh Pinnacle price with
a bet-at-home quote from the morning would invent gaps that never existed.

So the app refreshes these odds itself inside the same pre-kickoff window
that refreshes Pinnacle, at most once per competition per REFRESH_INTERVAL.
Each fetch costs about 0.3 cents per fixture on Apify.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "book_odds" / "latest.json"
ACTOR = "piotrv1001~oddsportal-scraper"
BOOKMAKER = "bet-at-home.de"
LEAGUES = {
    "soccer_uefa_champs_league": "https://www.oddsportal.com/football/europe/champions-league/",
    "soccer_germany_bundesliga": "https://www.oddsportal.com/football/germany/bundesliga/",
    "soccer_uefa_nations_league": "https://www.oddsportal.com/football/europe/uefa-nations-league/",
}
REFRESH_INTERVAL = timedelta(minutes=45)
# OddsPortal lists upcoming fixtures soonest first; a window's matches are at
# the top, so a small cap keeps a refresh cheap.
WINDOW_ITEMS = 15

_lock = threading.Lock()


def path() -> Path:
    return Path(os.getenv("BOOK_ODDS_PATH", str(DEFAULT_PATH)))


def load() -> dict:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"bookmaker": BOOKMAKER, "fixtures": [], "fetched_at": {}}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_league(sport_key: str, max_items: int, token: Optional[str] = None) -> list:
    """One OddsPortal read of a competition; returns bet-at-home fixtures."""
    token = token or os.environ["APIFY_TOKEN"]
    payload = {"startUrls": [{"url": LEAGUES[sport_key]}], "maxItems": max_items,
               "scrapeMatchMarkets": False,
               # The proxy country decides which bookmakers OddsPortal lists;
               # Germany returns exactly the ones licensed there.
               "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"],
                                      "apifyProxyCountry": "DE"}}
    request = urllib.request.Request(
        f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items?token={token}",
        method="POST", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        items = json.loads(response.read().decode())
    stamp = _now().isoformat()
    out = []
    for m in items:
        offer = next((b for b in m.get("bookmakerOdds", []) if b.get("bookmaker") == BOOKMAKER), None)
        if not offer or not all(offer.get(k) for k in ("home", "draw", "away")):
            continue
        out.append({"sport_key": sport_key, "home_team": m["homeTeam"], "away_team": m["awayTeam"],
                    "commence_time": m["startTime"], "fetched_at": stamp,
                    "odds": {k: float(offer[k]) for k in ("home", "draw", "away")}})
    return out


def store(sport_key: str, fixtures: list) -> None:
    """Replace one competition's fixtures, keeping the others."""
    with _lock:
        data = load()
        data["fixtures"] = [f for f in data.get("fixtures", []) if f.get("sport_key") != sport_key] + fixtures
        stamps = data.get("fetched_at") if isinstance(data.get("fetched_at"), dict) else {}
        stamps[sport_key] = _now().isoformat()
        data["fetched_at"] = stamps
        data["bookmaker"] = BOOKMAKER
        path().parent.mkdir(parents=True, exist_ok=True)
        path().write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def refresh_if_due(sport_key: str) -> bool:
    """Fetch a competition when its stored odds are older than the interval.

    Called from the pre-kickoff window. Returns True if a fetch happened.
    Failures are swallowed: without fresh odds the tip simply says so, which
    is better than a request failing on a scraper.
    """
    if sport_key not in LEAGUES or not os.getenv("APIFY_TOKEN"):
        return False
    stamps = load().get("fetched_at")
    last = stamps.get(sport_key) if isinstance(stamps, dict) else None
    try:
        if last and _now() - datetime.fromisoformat(last) < REFRESH_INTERVAL:
            return False
    except ValueError:
        pass
    try:
        store(sport_key, fetch_league(sport_key, WINDOW_ITEMS))
        return True
    except Exception:
        return False

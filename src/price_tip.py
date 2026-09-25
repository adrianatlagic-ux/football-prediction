"""The price tip: where a usable bookmaker pays more than a bet is worth.

Every attempt in this project to beat the market by forming a better opinion
about a match failed - our model, learned selectors, a language model given
every signal. Pinnacle's closing price proved well calibrated across 1,224
matches, with no systematic bias by odds level, outcome or club. The one
positive result was a pricing one: a German-licensed bookmaker sometimes
quotes above Pinnacle's margin-free price, and bet-at-home did so most often
at ordinary odds (scripts/german_books_vs_pinnacle.py).

So the tip is deliberately model-free. It takes Pinnacle's price as the fair
estimate, removes the margin, and flags the outcome where bet-at-home pays at
least THRESHOLD more than that. No model, no AI, no squad data enters the
decision; the blend test showed the model holds no information Pinnacle lacks
and would only dilute the tip (scripts/does_the_model_add_anything.py).

Whether the model and the AI agree with the tipped outcome is reported next
to it, for reading, not for choosing.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

# Fixed before the archive test was read, and kept: lowering it chases noise,
# raising it leaves almost nothing to tip.
THRESHOLD = 0.02
# How far apart the two sources may list a kickoff and still be the same match.
KICKOFF_TOLERANCE = timedelta(minutes=90)
# Older bookmaker odds are not shown as a tip: the gap could be a price that
# has long since moved.
MAX_BOOK_AGE = timedelta(hours=30)

OUTCOMES = (("home_win", "home"), ("draw", "draw"), ("away_win", "away"))
_GENERIC = {"fc", "sc", "cf", "ac", "afc", "vfl", "vfb", "tsg", "sv", "fk", "sk", "cd", "rb", "1", "04", "05",
            "1899", "1846", "borussia", "bayer", "eintracht", "de", "the", "united", "city", "real", "club"}


# Short forms OddsPortal uses that share no word with the Odds API's name.
_ABBREVIATIONS = {"psg": "paris saint germain"}
# Letters that NFKD does not decompose into a base letter plus an accent.
_LETTERS = str.maketrans({"ø": "o", "æ": "ae", "ß": "ss", "ł": "l", "đ": "d", "ı": "i"})


def _tokens(name: str) -> set:
    s = (name or "").lower().translate(_LETTERS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    for sep in ".-/'":
        s = s.replace(sep, " ")
    s = " ".join(_ABBREVIATIONS.get(w, w) for w in s.split())
    return {w for w in s.split() if len(w) > 1 and w not in _GENERIC}


def _time(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def pinnacle_prices(event: dict) -> Optional[dict]:
    """Pinnacle's 1X2 for an Odds API event, keyed home/draw/away, or None."""
    book = next((b for b in event.get("bookmakers", []) if b.get("key") == "pinnacle"), None)
    market = next((m for m in (book or {}).get("markets", []) if m.get("key") == "h2h"), None)
    if not market:
        return None
    by_name = {o["name"]: float(o["price"]) for o in market.get("outcomes", [])}
    prices = {"home": by_name.get(event.get("home_team")), "draw": by_name.get("Draw"),
              "away": by_name.get(event.get("away_team"))}
    if any(p is None or p <= 1 for p in prices.values()):
        return None
    return {**prices, "last_update": market.get("last_update") or book.get("last_update")}


def fair_probabilities(prices: dict) -> dict:
    """Margin removed proportionally - the standard, and the one the tests used."""
    implied = {k: 1 / prices[k] for k in ("home", "draw", "away")}
    total = sum(implied.values())
    return {k: v / total for k, v in implied.items()}


def match_fixture(event: dict, fixtures: list) -> Optional[dict]:
    """The bookmaker's listing of the same match, or None when unsure.

    The two sources spell teams differently ("Bayern Munich" / "Bayern
    München", "Paris Saint Germain" / "PSG"), so a match needs the same
    competition, a kickoff within tolerance, and a shared name token for both
    sides. Anything ambiguous returns None: no tip is better than a tip
    priced against the wrong game.
    """
    kickoff = _time(event.get("commence_time"))
    if kickoff is None:
        return None
    home, away = _tokens(event.get("home_team")), _tokens(event.get("away_team"))
    candidates = []
    for f in fixtures:
        if f.get("sport_key") != event.get("sport_key"):
            continue
        start = _time(f.get("commence_time"))
        if start is None or abs(start - kickoff) > KICKOFF_TOLERANCE:
            continue
        if home & _tokens(f.get("home_team")) and away & _tokens(f.get("away_team")):
            candidates.append(f)
    return candidates[0] if len(candidates) == 1 else None


def build_price_tip(event: dict, book: dict, now: Optional[datetime] = None) -> dict:
    """Compare the bookmaker against Pinnacle's fair price for one event.

    Always returns every outcome's numbers, so the page can show why there is
    or is not a tip. `tip` is the outcome with the largest edge if that edge
    clears THRESHOLD, else None.
    """
    now = now or datetime.now(timezone.utc)
    bookmaker = book.get("bookmaker")
    base = {"bookmaker": bookmaker, "threshold": THRESHOLD, "tip": None,
            "book_fetched_at": None, "outcomes": []}

    pinnacle = pinnacle_prices(event)
    if pinnacle is None:
        return {**base, "reason": "Pinnacle does not price this match, so there is no fair reference."}
    base["pinnacle_updated_at"] = pinnacle.get("last_update")

    fixture = match_fixture(event, book.get("fixtures", []))
    if fixture is None:
        return {**base, "reason": f"{bookmaker} has no listing for this match that we could match safely."}

    # Each fixture carries the time of the fetch that produced it; older files
    # stamped the whole book once.
    stamp = fixture.get("fetched_at") or book.get("fetched_at")
    stamp = stamp.get(event.get("sport_key")) if isinstance(stamp, dict) else stamp
    base["book_fetched_at"] = stamp
    fetched = _time(stamp)
    if fetched is None or now - fetched > MAX_BOOK_AGE:
        return {**base, "reason": f"{bookmaker} odds are too old to compare against current prices."}

    fair = fair_probabilities(pinnacle)
    rows = []
    for outcome, key in OUTCOMES:
        offered = float(fixture["odds"][key])
        rows.append({
            "market": "1X2", "outcome": outcome,
            "team": event.get("home_team") if key == "home" else event.get("away_team") if key == "away" else None,
            "book_odds": round(offered, 2),
            "pinnacle_odds": round(pinnacle[key], 2),
            "fair_odds": round(1 / fair[key], 2),
            "probability": round(fair[key], 4),
            # Expected return per unit staked, judged by Pinnacle's estimate.
            "edge": round(offered * fair[key] - 1, 4),
        })
    best = max(rows, key=lambda r: r["edge"])
    tip = best if best["edge"] >= THRESHOLD else None
    reason = None if tip else (
        f"{bookmaker} pays less than the fair price on every outcome here "
        f"(closest: {best['edge']:+.1%}).")
    return {**base, "outcomes": rows, "tip": tip, "reason": reason}


def model_and_ai_view(tip: Optional[dict], prediction: dict, agent_eval: Optional[dict]) -> dict:
    """Whether the model and the AI side with the tipped outcome - display only.

    The model "agrees" when it rates the outcome at least as likely as
    Pinnacle does. Neither view changes the tip: among bet-at-home's archived
    opportunities, the ones the model liked did worse, not better.
    """
    if not tip:
        return {"model_agrees": None, "ai_agrees": None, "model_probability": None}
    key = {"home_win": "probability_home_win", "draw": "probability_draw",
           "away_win": "probability_away_win"}[tip["outcome"]]
    model_p = prediction.get(key)
    model_agrees = None if model_p is None else float(model_p) >= tip["probability"]
    pick = (agent_eval or {}).get("pick")
    ai_agrees = None if not agent_eval else bool(
        pick and pick.get("market") == "1X2" and pick.get("outcome") == tip["outcome"])
    return {"model_agrees": model_agrees, "ai_agrees": ai_agrees,
            "model_probability": None if model_p is None else round(float(model_p), 4)}

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
# A tip needs both prices read together. Numbers from a morning read are
# still shown, for orientation, but never tipped: the gap may have closed.
ALIGNMENT = timedelta(minutes=30)
# Pinnacle is read in each match's last hour and moves constantly then; a
# price it has not touched for this long is a stale feed, not a quiet market.
MAX_PINNACLE_AGE = timedelta(hours=6)

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


def _pinnacle_two_way(event: dict, key: str, first: tuple, second: tuple) -> Optional[tuple]:
    """Pinnacle's margin-free pair for one exact line, or None if it has none.

    `first`/`second` are (outcome name, point). Pinnacle quotes one main line
    per market here, usually a quarter line, so most .5 lines have no match -
    and a line it does not quote is never estimated.
    """
    book = next((b for b in event.get("bookmakers", []) if b.get("key") == "pinnacle"), None)
    market = next((m for m in (book or {}).get("markets", []) if m.get("key") == key), None)
    if not market:
        return None
    prices = []
    for name, point in (first, second):
        o = next((o for o in market.get("outcomes", [])
                  if o.get("name") == name and o.get("point") == point), None)
        if not o or float(o["price"]) <= 1:
            return None
        prices.append(float(o["price"]))
    p1, p2 = 1 / prices[0], 1 / prices[1]
    return prices[0], p1 / (p1 + p2)


def _row(market, outcome, team, offered, probability, pinnacle_odds=None, refund=0.0, side=None):
    """One comparable bet. `refund` is the chance the stake comes back (Draw
    No Bet on a draw); probability is then the chance of winning given no
    refund, and the edge counts the refund at stake value."""
    win = probability * (1 - refund)
    return {"market": market, "outcome": outcome, "team": team, "side": side,
            # The three ways the bet can end. Only Draw No Bet has a refund;
            # for it "probability" alone (the chance given no draw) reads
            # higher than the chance of actually winning, so all three are kept.
            "win_probability": round(win, 4), "refund_probability": round(refund, 4),
            "loss_probability": round(1 - win - refund, 4),
            "book_odds": round(offered, 2),
            "pinnacle_odds": round(pinnacle_odds, 2) if pinnacle_odds else None,
            "fair_odds": round(1 / probability, 2), "probability": round(probability, 4),
            # Expected return per unit staked, judged by Pinnacle's estimate.
            "edge": round(offered * win + refund - 1, 4)}


def _handicap_label(point: float) -> str:
    return f"Handicap {'+' if point > 0 else ''}{point}"


def market_rows(event: dict, fixture: dict, fair: dict) -> list:
    """Every bet-at-home market that Pinnacle prices exactly.

    From Pinnacle's 1X2 alone: Double Chance and Asian Handicap +/-0.5 (a
    team +0.5 is win-or-draw, -0.5 is win) and Draw No Bet. Other Over/Under
    and Asian Handicap lines only where Pinnacle quotes the very same line.
    """
    markets = fixture.get("markets") or {}
    home, away = event.get("home_team"), event.get("away_team")
    h, d, a = fair["home"], fair["draw"], fair["away"]
    exact = {("home", 0.5): h + d, ("home", -0.5): h, ("away", 0.5): a + d, ("away", -0.5): a}
    rows = []
    # Win-or-lose lines only (x.5), plus Draw No Bet at 0: a quarter line
    # splits the stake across two bets, and whole lines refund on the number.
    def usable(point):
        return point is not None and (point % 1 == 0.5 or point == 0)

    for line in markets.get("spreads", []):
        if not usable(line.get("point")):
            continue
        # "+ 0.0" turns the away side of Draw No Bet from -0.0 into 0.0.
        for side, team, point in (("home", home, line["point"] + 0.0), ("away", away, -line["point"] + 0.0)):
            offered = line.get(side)
            if not offered or offered <= 1:
                continue
            label = _handicap_label(point)
            if point == 0:
                win, lose = (h, a) if side == "home" else (a, h)
                rows.append(_row(label, "handicap", team, offered, win / (win + lose), refund=d, side=side))
            elif (side, point) in exact:
                rows.append(_row(label, "handicap", team, offered, exact[(side, point)], side=side))
            else:
                pair = _pinnacle_two_way(event, "spreads", (team, point),
                                         (away if side == "home" else home, -point))
                if pair:
                    rows.append(_row(label, "handicap", team, offered, pair[1], pinnacle_odds=pair[0], side=side))
    for line in markets.get("totals", []):
        if not usable(line.get("point")) or line.get("point") == 0:
            continue
        for side, other in (("Over", "Under"), ("Under", "Over")):
            offered = line.get(side.lower())
            pair = _pinnacle_two_way(event, "totals", (side, line["point"]), (other, line["point"]))
            if offered and offered > 1 and pair:
                rows.append(_row(f"Over/Under {line['point']}", side, None, offered, pair[1],
                                 pinnacle_odds=pair[0]))
    return rows


def build_price_tip(event: dict, book: dict, now: Optional[datetime] = None) -> dict:
    """Compare the bookmaker against Pinnacle's fair price for one event.

    Always returns every comparable bet's numbers, so the page can show why
    there is or is not a tip. `tip` is the bet with the largest edge if that
    edge clears THRESHOLD, else None.
    """
    now = now or datetime.now(timezone.utc)
    bookmaker = book.get("bookmaker")
    # Everything needed to audit the tip later, stored whether or not a tip
    # was given: which rule chose it, and when each side's price was read.
    base = {"bookmaker": bookmaker, "threshold": THRESHOLD, "tip": None,
            "rule": "largest_edge_over_pinnacle_fair_v1",
            "pinnacle_fetched_at": event.get("odds_fetched_at"),
            "book_fetched_at": None, "book_markets_fetched_at": None, "outcomes": []}

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
    base["book_markets_fetched_at"] = fixture.get("markets_fetched_at")
    fetched = _time(stamp)
    if fetched is None or now - fetched > MAX_BOOK_AGE:
        return {**base, "reason": f"{bookmaker} odds are too old to compare against current prices."}

    snapshot = _time(event.get("odds_fetched_at"))

    def aligned(value) -> bool:
        t = _time(value)
        return t is not None and (snapshot is None or abs(snapshot - t) <= ALIGNMENT)

    pinnacle_time = _time(pinnacle.get("last_update"))
    reference = snapshot or now
    pinnacle_fresh = pinnacle_time is not None and reference - pinnacle_time <= MAX_PINNACLE_AGE

    fair = fair_probabilities(pinnacle)
    rows = []
    for outcome, key in OUTCOMES:
        rows.append(_row("1X2", outcome,
                         event.get("home_team") if key == "home" else event.get("away_team") if key == "away" else None,
                         float(fixture["odds"][key]), fair[key], pinnacle_odds=pinnacle[key], side=key))
    # The full book comes from its own, rarer fetch and is only compared when
    # it was read together with this Pinnacle price.
    full_book = bool(fixture.get("markets")) and aligned(fixture.get("markets_fetched_at"))
    if full_book:
        rows += market_rows(event, fixture, fair)
    base["full_book"] = full_book
    best = max(rows, key=lambda r: r["edge"])
    if not pinnacle_fresh:
        tip, reason = None, ("Pinnacle's price has no recent update time, so it may be stale. "
                             "No tip is given on it.")
    elif not aligned(stamp):
        tip, reason = None, (f"{bookmaker}'s odds were read at a different time than Pinnacle's. "
                             "A tip is only given when both are read together, in the hour before kickoff.")
    elif best["edge"] >= THRESHOLD:
        tip, reason = best, None
    else:
        tip, reason = None, (f"{bookmaker} pays less than the fair price on every comparable bet here "
                             f"(closest: {best['edge']:+.1%}).")
    return {**base, "outcomes": rows, "tip": tip, "reason": reason}


def _same(a: dict, b: dict) -> bool:
    return bool(a and b and a.get("market") == b.get("market") and a.get("outcome") == b.get("outcome")
                and (a.get("team") or None) == (b.get("team") or None))


def model_and_ai_view(tip: Optional[dict], prediction: dict, agent_eval: Optional[dict],
                      candidates: Optional[list] = None) -> dict:
    """Whether the model and the AI side with the tipped bet - display only.

    The model "agrees" when it rates the bet at least as likely as Pinnacle
    does. Neither view changes the tip: among bet-at-home's archived
    opportunities, the ones the model liked did worse, not better.
    """
    if not tip:
        return {"model_agrees": None, "ai_agrees": None, "model_probability": None}
    try:
        h, d, a = (float(prediction[k]) for k in ("probability_home_win", "probability_draw",
                                                    "probability_away_win"))
    except (KeyError, TypeError, ValueError):
        h = d = a = None
    model_p = None
    if tip["market"] == "1X2":
        model_p = prediction.get({"home_win": "probability_home_win", "draw": "probability_draw",
                                  "away_win": "probability_away_win"}[tip["outcome"]])
    elif h is not None and tip["market"] in ("Handicap +0.5", "Handicap -0.5", "Handicap 0.0"):
        # The Odds API and our cache may spell a team differently; the row
        # records which side it is.
        is_home = tip.get("side") == "home"
        win, lose = (h, a) if is_home else (a, h)
        model_p = {"Handicap +0.5": win + d, "Handicap -0.5": win,
                   "Handicap 0.0": win / (win + lose) if win + lose else None}[tip["market"]]
    else:
        match = next((c for c in candidates or [] if _same(c, tip)), None)
        model_p = match.get("model_probability_raw") if match else None
    model_agrees = None if model_p is None else float(model_p) >= tip["probability"]
    pick = (agent_eval or {}).get("pick")
    ai_agrees = None if not agent_eval else _same(pick, tip)
    return {"model_agrees": model_agrees, "ai_agrees": ai_agrees,
            "model_probability": None if model_p is None else round(float(model_p), 4)}

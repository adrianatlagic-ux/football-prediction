from __future__ import annotations

import json
import math
import unicodedata
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.club_predictor import ClubFootballPredictor as FootballPredictor

from src.club_predictor import DEFAULT_MODEL_PATH as MODEL_PATH
PREDICTIONS_CACHE_DIR = Path(__file__).parent.parent / "data" / "predictions_cache"

app = FastAPI(
    title="Football Prediction API",
    description="Predict football match outcomes using machine learning.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_predictor: FootballPredictor | None = None
_national_predictor = None

# Club and national football need separate models: the national one carries
# FIFA-ranking features and a neutral-venue flag that have no club
# equivalent, and the club one carries squad market values that have no
# national equivalent. Which one answers is decided by the teams involved,
# not by a flag the caller has to remember to set.
NATIONAL_MODEL_PATH = Path(os.getenv("NATIONAL_MODEL_PATH", "model.joblib"))


def _get_predictor() -> FootballPredictor:
    global _predictor
    if _predictor is None:
        _predictor = FootballPredictor(model_path=MODEL_PATH if MODEL_PATH.exists() else None)
        if not _predictor._trained:
            raise HTTPException(status_code=503, detail="Modell nicht trainiert. POST /train aufrufen.")
    return _predictor


def _get_national_predictor():
    global _national_predictor
    if _national_predictor is None:
        from src.predictor import FootballPredictor as NationalPredictor
        _national_predictor = NationalPredictor(
            model_path=NATIONAL_MODEL_PATH if NATIONAL_MODEL_PATH.exists() else None)
        if not _national_predictor._trained:
            raise HTTPException(status_code=503,
                                detail="Nationalmannschafts-Modell nicht trainiert.")
    return _national_predictor


def _is_national_fixture(home_team: str, away_team: str) -> bool:
    """True when both sides are national teams we have a ranking for.

    Requiring BOTH keeps a club whose name happens to collide with a country
    from being routed to the national model. Falls back to the club model on
    any doubt, which is the status quo rather than a new failure mode.
    """
    from src.fifa_rankings import has_ranking
    return has_ranking(home_team) and has_ranking(away_team)


def _predictor_for(home_team: str, away_team: str):
    if _is_national_fixture(home_team, away_team) and NATIONAL_MODEL_PATH.exists():
        return _get_national_predictor()
    return _get_predictor()


# ── Request / Response Models ──────────────────────────────────────────────

class TrainResponse(BaseModel):
    accuracy: float
    log_loss: Optional[float] = None
    message: str


class PredictRequest(BaseModel):
    home_team: str
    away_team: str
    neutral: Optional[bool] = None  # None = auto (WM-Gastgeber kriegen Heimvorteil)


class ScorePrediction(BaseModel):
    home_xg: float
    away_xg: float
    most_likely_score: str
    result: str
    probability_home_win: float
    probability_draw: float
    probability_away_win: float
    top_scorelines: list[dict]
    betting_markets: dict[str, Any] = {}
    score_matrix: Optional[list[list[float]]] = None


class GameFlow(BaseModel):
    match_type: str
    match_description: str
    dominance_index: float
    total_xg: float
    first_goal: dict[str, Any]
    halftime_xg: dict[str, float]
    top_halftime_scores: list[dict]
    goal_timing: dict[str, Any]
    comeback_probability: dict[str, float]
    late_drama_probability: float
    match_stories: list[dict]
    predicted_stats: dict[str, Any]
    match_ticker: list[dict]


class PredictResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_version: Optional[str] = None
    generated_at: Optional[str] = None
    training_end: Optional[str] = None
    market_value_policy: Optional[str] = None
    home_team: str
    away_team: str
    prediction: str                  # H / D / A
    prediction_label: str            # "Home Win" / "Draw" / "Away Win"
    probability_home_win: float
    probability_draw: float
    probability_away_win: float
    score_prediction: ScorePrediction
    game_flow: GameFlow
    explanation: dict[str, Any]


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    pred = _predictor
    return {
        "status": "ok",
        "model_loaded": pred is not None and pred._trained,
        "model_path": str(MODEL_PATH),
    }


@app.post("/train", response_model=TrainResponse)
async def train(file: Optional[UploadFile] = File(None)):
    global _predictor
    p = FootballPredictor()
    data_path = None

    if file:
        tmp = Path("/tmp") / file.filename
        tmp.write_bytes(await file.read())
        data_path = tmp

    try:
        metrics = p.train(data_path=data_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    p.save(MODEL_PATH)
    _predictor = p

    return TrainResponse(
        accuracy=metrics["accuracy"],
        log_loss=metrics.get("log_loss"),
        message="Modell trainiert und gespeichert.",
    )


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    predictor = _predictor_for(req.home_team, req.away_team)
    try:
        result = predictor.predict_match(
            req.home_team,
            req.away_team,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return PredictResponse(
        model_version=result.get("model_version"),
        generated_at=result.get("generated_at"),
        training_end=result.get("training_end"),
        market_value_policy=result.get("market_value_policy"),
        home_team=result["home_team"],
        away_team=result["away_team"],
        prediction=result["prediction"],
        prediction_label=result["prediction_label"],
        probability_home_win=result["probability_home_win"],
        probability_draw=result["probability_draw"],
        probability_away_win=result["probability_away_win"],
        score_prediction=ScorePrediction(**result["score_prediction"]),
        game_flow=GameFlow(**result["game_flow"]),
        explanation=result["explanation"],
    )


@app.get("/predict")
def predict_get(home_team: str, away_team: str, neutral: Optional[bool] = None):
    """GET-Variante für schnelle Tests im Browser."""
    return predict(PredictRequest(home_team=home_team, away_team=away_team, neutral=neutral))


# ── Gespeicherte Vorhersagen (für Konsistenz Social Media <-> Website) ──────
#
# n8n generiert pro Match einmal Prediction + Spielverlauf + Texte/Bilder und
# speichert das Gesamtergebnis hier ab (POST). Die Website holt sich später
# exakt diesen gespeicherten Stand (GET) - so steht auf Instagram/TikTok und
# der Website garantiert dasselbe, auch wenn der Workflow erneut laufen würde.

_MATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _cache_path(match_id: str) -> Path:
    if not _MATCH_ID_RE.match(match_id):
        raise HTTPException(status_code=400, detail="Ungültige match_id.")
    return PREDICTIONS_CACHE_DIR / f"{match_id}.json"


@app.post("/predictions/{match_id}")
def save_prediction(match_id: str, payload: dict[str, Any]):
    PREDICTIONS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(match_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "match_id": match_id}


@app.get("/predictions/{match_id}")
def get_prediction(match_id: str):
    path = _cache_path(match_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Keine gespeicherte Vorhersage für diese match_id.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/predictions")
def list_predictions():
    if not PREDICTIONS_CACHE_DIR.exists():
        return {"match_ids": []}
    return {"match_ids": sorted(p.stem for p in PREDICTIONS_CACHE_DIR.glob("*.json"))}


# ── ESPN Real Results ──────────────────────────────────────────────────────

_ESPN_NAME_MAP = {
    "Czechia": "Czech Republic",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Türkiye": "Turkey",
    "Curaçao": "Curacao",
    "Ivory Coast": "Ivory Coast",
    "Congo DR": "DR Congo",
    "USA": "United States",
}

_espn_cache: dict[str, Any] = {}
_espn_cache_ts: float = 0
_ESPN_TTL = 180  # seconds


def _espn_team(name: str) -> str:
    return _ESPN_NAME_MAP.get(name, name)


def _fetch_espn_results() -> list[dict]:
    results = []
    errors = []
    for league, sport in (("uefa.champions", "soccer_uefa_champs_league"),
                          ("ger.1", "soccer_germany_bundesliga"),
                          ("ger.2", "soccer_germany_bundesliga2")):
        try:
            results.extend(_fetch_espn_league(league, sport))
        except Exception as exc:
            errors.append(exc)
    if not results and errors:
        raise errors[0]
    return results


def _fetch_espn_league(league, sport) -> list[dict]:
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?limit=100"
    # Deliberately no User-Agent header. ESPN answers 403 to a spoofed browser
    # UA ("Mozilla/5.0") and 200 to Python's default one, so the header that
    # was meant to look harmless is what broke /real-results. The Odds API
    # calls below are unaffected and keep theirs.
    with urllib.request.urlopen(url, timeout=8) as resp:
        data = json.loads(resp.read())

    results = []
    for event in data.get("events", []):
        comp = event["competitions"][0]
        status = comp["status"]["type"]
        completed = status.get("completed", False)

        competitors = comp["competitors"]
        # ESPN: index 0 = home, index 1 = away
        home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home_team = _espn_team(home_c["team"]["displayName"])
        away_team = _espn_team(away_c["team"]["displayName"])

        def stat(competitor, name):
            for s in competitor.get("statistics", []):
                if s.get("name") == name:
                    try:
                        return float(s["displayValue"])
                    except (KeyError, ValueError):
                        return None
            return None

        # Build team id -> which side map for events
        home_id = home_c["team"]["id"]

        events = []
        for d in comp.get("details", []):
            if not d.get("scoringPlay") and not d.get("yellowCard") and not d.get("redCard"):
                continue
            minute = d.get("clock", {}).get("displayValue", "")
            team_id = d.get("team", {}).get("id")
            athletes = [a.get("displayName", "") for a in d.get("athletesInvolved", [])]
            evt_type = "goal" if d.get("scoringPlay") else ("red_card" if d.get("redCard") else "yellow_card")
            events.append({
                "type": evt_type,
                "minute": minute,
                "team": home_team if team_id == home_id else away_team,
                "player": athletes[0] if athletes else "",
                "own_goal": d.get("ownGoal", False),
                "penalty": d.get("penaltyKick", False),
            })

        results.append({
            "result_event_id": event.get("id"),
            "sport_key": sport,
            "commence_time": event.get("date"),
            # Extra time/penalty outcomes must never settle a 90-minute bet.
            "score_scope": "regulation" if status.get("name") in ("STATUS_FULL_TIME", "STATUS_FINAL") and comp["status"].get("period") == 2 else "unverified",
            "home_team": home_team,
            "away_team": away_team,
            "home_score": int(home_c.get("score", 0)) if completed else None,
            "away_score": int(away_c.get("score", 0)) if completed else None,
            "completed": completed,
            "status": status.get("description", ""),
            "events": events,
            "stats": {
                "home": {
                    "possession": stat(home_c, "possessionPct"),
                    "shots": stat(home_c, "totalShots"),
                    "shots_on_target": stat(home_c, "shotsOnTarget"),
                    "corners": stat(home_c, "wonCorners"),
                    "fouls": stat(home_c, "foulsCommitted"),
                },
                "away": {
                    "possession": stat(away_c, "possessionPct"),
                    "shots": stat(away_c, "totalShots"),
                    "shots_on_target": stat(away_c, "shotsOnTarget"),
                    "corners": stat(away_c, "wonCorners"),
                    "fouls": stat(away_c, "foulsCommitted"),
                },
            },
        })
    return results


def _get_espn_results() -> list[dict]:
    global _espn_cache, _espn_cache_ts
    now = time.time()
    if not _espn_cache or (now - _espn_cache_ts) > _ESPN_TTL:
        try:
            _espn_cache = _fetch_espn_results()
            _espn_cache_ts = now
        except Exception as exc:
            if not _espn_cache:
                raise
    return _espn_cache


@app.get("/real-results")
def real_results():
    try:
        return {"results": _get_espn_results()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ESPN API unavailable: {exc}")


# ── Value Betting (The Odds API) ────────────────────────────────────────────

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
# Daily at 15:00 UTC, plus one event-only refresh during its final hour.
# Requests trigger due work; the GitHub logger is the periodic caller.
# This is not an exact-time scheduler and its calls consume provider credits.
ODDS_REFRESH_HOUR_UTC = 15
_odds_cache: list[dict] = []
_odds_cache_date: str | None = None
_odds_cache_fetched_at = 0.0
_odds_daily_refresh_date = None
_final_odds_cache = {}
_final_odds_attempts = {}
_odds_refresh_lock = threading.Lock()
ODDS_CACHE_TTL_SECONDS = int(os.getenv("ODDS_CACHE_TTL_SECONDS", "0"))  # 0 retains daily quota policy

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Agent picks are computed once per match per day, anchored to the same clock
# time as the odds refresh - one Gemini call per match that has odds that day,
# not per request. Keeps volume identical to (and as predictable as) the odds.
_agent_picks_cache: dict[tuple[str, str], dict] = {}
_agent_picks_cache_date: str | None = None

# Vorteile über dieser Grenze sind praktisch immer ein Modellfehler, kein echter
# Value - sie werden nicht als Empfehlung ausgesprochen. Tiefer = konservativer.
REALISTIC_EV_CEILING = 0.25


# The site covers club competitions only (Champions League, Bundesliga) - no
# World Cup fixtures exist anymore, so odds are pulled from each covered
# league's own sport key and merged into one pool. _find_odds_match() below
# matches by team name regardless of which league an event came from, so a
# single merged list is all the rest of the odds/value-bet code needs.
ODDS_SPORT_KEYS = ["soccer_uefa_champs_league", "soccer_germany_bundesliga"]


def _fetch_odds() -> list[dict]:
    if not ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="ODDS_API_KEY ist nicht konfiguriert.")
    events: list[dict] = []
    last_error: Exception | None = None
    for sport_key in ODDS_SPORT_KEYS:
        url = (
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
            f"?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals,spreads&oddsFormat=decimal"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                events.extend(json.loads(resp.read()))
        except Exception as exc:
            last_error = exc
    if not events and last_error is not None:
        raise last_error
    return events


def _fetch_event_odds(event):
    """Refresh only the event's own competition, including Bundesliga."""
    sport, event_id = event.get("sport_key"), event.get("id")
    if sport not in ODDS_SPORT_KEYS or not event_id:
        raise ValueError("Unknown event identity")
    url = (f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds"
           f"?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals,spreads&oddsFormat=decimal")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        fresh = json.loads(resp.read())
    if any(fresh.get(k) != event.get(k) for k in ("id", "sport_key", "home_team", "away_team", "commence_time")):
        raise ValueError("Refreshed event identity changed")
    return fresh


def _get_odds() -> list[dict]:
    from src.bet_audit import timestamp
    from src.odds_schedule import stamp_event
    global _odds_cache, _odds_cache_date, _odds_cache_fetched_at, _odds_daily_refresh_date
    # Serialize provider requests so concurrent page/logger calls cannot issue
    # duplicate paid refreshes. The final snapshot survives later daily loads.
    with _odds_refresh_lock:
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        due = now.hour >= ODDS_REFRESH_HOUR_UTC and _odds_daily_refresh_date != today
        ttl_expired = ODDS_CACHE_TTL_SECONDS > 0 and time.time() - _odds_cache_fetched_at >= ODDS_CACHE_TTL_SECONDS
        if not _odds_cache or due or ttl_expired:
            try:
                events = _fetch_odds()
                fetched = datetime.now(timezone.utc)
                stage = "daily" if fetched.hour >= ODDS_REFRESH_HOUR_UTC else "initial"
                _odds_cache = [stamp_event(e, fetched, stage) for e in events]
                _odds_cache_date = fetched.date().isoformat()
                _odds_cache_fetched_at = time.time()
                if stage == "daily":
                    _odds_daily_refresh_date = fetched.date().isoformat()
            except Exception:
                if not _odds_cache:
                    raise
        output = []
        for event in _odds_cache:
            try:
                seconds = (timestamp(event["commence_time"]) - datetime.now(timezone.utc)).total_seconds()
            except (KeyError, ValueError, TypeError):
                output.append(event)
                continue
            key = (event.get("sport_key"), event.get("id"), event["commence_time"])
            if 0 < seconds <= 3600 and key not in _final_odds_cache:
                # Failed refreshes retry at most every 15 minutes. They do not
                # turn an old daily snapshot into a purported final snapshot.
                previous = _final_odds_attempts.get(key)
                if previous is None or time.time() - previous >= 900:
                    _final_odds_attempts[key] = time.time()
                    try:
                        fresh = _fetch_event_odds(event)
                        _final_odds_cache[key] = stamp_event(fresh, datetime.now(timezone.utc), "final")
                    except Exception:
                        pass
            selected = _final_odds_cache.get(key, event)
            if 0 < seconds <= 3600 and key not in _final_odds_cache:
                selected = {**selected, "final_refresh_status": "pending_or_failed"}
            output.append(selected)
        return output


# The Odds API uses different team names than our fixtures for a few
# countries. Keyed/valued by the post-normalization (letters-only) form.
_ODDS_TEAM_ALIASES = {
    "usa": "unitedstates",
}


def _norm_team(name: str) -> str:
    # The Odds API writes "Bosnia & Herzegovina", we write "...and...".
    # Strip "and"/"&" as a standalone joiner so both normalize the same way,
    # without cutting "and" out of names like "Iceland".
    from scripts.build_club_training_data import _canon
    name = unicodedata.normalize("NFKD", _canon(name)).encode("ascii", "ignore").decode()
    name = re.sub(r"\band\b", " ", name.lower())
    name = name.replace("&", " ")
    norm = re.sub(r"[^a-z]", "", name)
    return _ODDS_TEAM_ALIASES.get(norm, norm)


def _find_odds_match(odds: list[dict], home_team: str, away_team: str) -> Optional[dict]:
    h, a = _norm_team(home_team), _norm_team(away_team)
    matches = [event for event in odds if h and a
               and _norm_team(event.get("home_team", "")) == h
               and _norm_team(event.get("away_team", "")) == a]
    # Never reuse a home prediction for the reverse leg or choose arbitrarily
    # between two events with the same teams. An exact event API can be added.
    return matches[0] if len(matches) == 1 else None


def _available_prices(event: dict, market_key: str, outcome_name: str, point: Optional[float] = None) -> list[dict]:
    from src.bet_selection import quote_is_fresh
    from src.bet_audit import timestamp
    as_of = timestamp(event["odds_fetched_at"]) if event.get("odds_fetched_at") else None
    offers = {}
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != market_key:
                continue
            if not quote_is_fresh(market.get("last_update") or bm.get("last_update"), as_of):
                continue
            for outcome in market.get("outcomes", []):
                if outcome.get("name") != outcome_name:
                    continue
                if point is not None and outcome.get("point") != point:
                    continue
                price = outcome.get("price")
                if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 1:
                    continue
                key = bm.get("key") or bm.get("title")
                if key and (key not in offers or price > offers[key]["price"]):
                    offers[key] = {"price": price, "bookmaker": bm.get("title"), "bookmaker_key": key,
                                   "last_update": market.get("last_update") or bm.get("last_update")}
    return list(offers.values())


def _best_price(event, market_key, outcome_name, point=None):
    return max(_available_prices(event, market_key, outcome_name, point), key=lambda o: o["price"], default=None)


@app.get("/odds")
def get_odds():
    try:
        return {"events": _get_odds()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Odds API unavailable: {exc}")


def _compute_value_bets(prediction: dict, odds: list[dict], home_team: str, away_team: str, include_offers=False) -> dict:
    event = _find_odds_match(odds, home_team, away_team)
    if event is None:
        return {"home_team": home_team, "away_team": away_team, "odds_found": False, "bets": []}

    # Once a match has kicked off, bookmaker odds become live/in-play odds that
    # react to the score and game state - but our model's probabilities are
    # fixed pre-match estimates that don't know any of that. Comparing the two
    # would produce meaningless "edges", so we don't recommend in-play matches.
    commence = event.get("commence_time")
    from src.bet_audit import timestamp
    try:
        kickoff = timestamp(commence)
    except (ValueError, TypeError):
        return {"home_team": home_team, "away_team": away_team, "odds_found": False,
                "bets": [], "exclusion": "invalid_kickoff"}
    if datetime.now(timezone.utc) >= kickoff:
        return {"home_team": home_team, "away_team": away_team, "commence_time": commence,
                "sport_key": event.get("sport_key"), "event_id": event.get("id"),
                "odds_found": True, "in_play": True, "recommendation": None,
                "recommendation_warning": False, "green_bets": [], "red_bets": [], "bets": []}

    from src.odds_schedule import snapshot_context
    context = snapshot_context(event)
    if not context["snapshot_valid"]:
        return {**context, "home_team": home_team, "away_team": away_team,
                "event_id": event.get("id"), "sport_key": event.get("sport_key"),
                "commence_time": commence, "odds_found": True, "bets": [],
                "exclusion": "scheduled_snapshot_expired"}
    quote_as_of = timestamp(context["odds_fetched_at"])
    candidates = []
    home_outcome_name, away_outcome_name = event["home_team"], event["away_team"]

    # If our own model is reasonably confident about who wins (>50%), a 1X2 bet
    # on a *different* outcome (e.g. recommending Draw while we ourselves
    # predict a clear win) contradicts our own headline prediction. Even if it
    # looks like "value" against the market, showing that as a clean top tip
    # undermines trust - so we flag it instead.
    h2h_probs = {
        "home_win": prediction["probability_home_win"],
        "draw": prediction["probability_draw"],
        "away_win": prediction["probability_away_win"],
    }
    predicted_winner = max(h2h_probs, key=h2h_probs.get)
    confident_favorite = h2h_probs[predicted_winner] > 0.5
    predicted_winner_team = (
        home_outcome_name if predicted_winner == "home_win"
        else away_outcome_name if predicted_winner == "away_win"
        else None
    )

    pricing_prediction = dict(prediction, home_team=home_outcome_name, away_team=away_outcome_name)
    pricing_exclusions = []

    def _add_candidate(market, outcome, team, prob, best, market_prob):
        from src.bet_selection import price_bet, quote_is_fresh, market_evidence
        bet = {"market": market, "outcome": outcome, "team": team, "best_odds": best["price"]}
        try:
            priced = price_bet(bet, pricing_prediction, prob)
        except (ValueError, KeyError, TypeError) as exc:
            pricing_exclusions.append({"market": market, "outcome": outcome, "reason": str(exc)})
            return
        prob = priced["probability"]
        binary_market = market == "1X2" or (market.startswith(("Handicap ", "Over/Under ")) and float(market.split()[-1]) % 1 == 0.5)
        market_prob = float(market_prob) if market_prob is not None and binary_market else None
        ev = priced["expected_value"]
        feed_key = "h2h" if market == "1X2" else "totals" if market.startswith("Over/Under") else "spreads"
        feed_name = (team or "Draw") if feed_key == "h2h" else outcome if feed_key == "totals" else team
        point = None if feed_key == "h2h" else float(market.split()[-1])
        reference = market_evidence(event, feed_key, feed_name, point, now=quote_as_of, exclude_book=best.get("bookmaker_key"))
        deviation = abs(prob - market_prob) if market_prob is not None else None
        # Retain the legacy contradiction guard as an explicit experimental
        # filter. It is not statistical proof that an underdog lacks value.
        contradicts_favorite = bool(
            confident_favorite and (
                (market == "1X2" and outcome != predicted_winner)
                or (market == "Handicap +0.5" and predicted_winner_team is not None and team != predicted_winner_team)
            )
        )
        candidates.append({
            "market": market,
            "outcome": outcome,
            "team": team,
            "probability": round(prob, 4),
            "market_probability": round(market_prob, 4) if market_prob is not None else None,
            "best_odds": best["price"],
            "bookmaker": best["bookmaker"],
            "bookmaker_key": best.get("bookmaker_key"),
            "selection_market_reference": reference,
            "quote_last_update": best.get("last_update"),
            "model_probability_raw": round(prob, 4),
            "expected_value": round(ev, 4),
            "kelly_stake_pct": round(priced["kelly_stake_pct"], 1),
            "kelly_stake_pct_raw": priced["kelly_stake_pct"],
            "push_probability": priced["push_probability"],
            "loss_probability": priced["loss_probability"],
            "payout_distribution": priced["payout_distribution"],
            "pricing_version": priced["pricing_version"],
            "quote_fresh": quote_is_fresh(best.get("last_update"), quote_as_of),
            "quote_freshness_basis": "at_snapshot_fetch",
            "odds_fetched_at": context["odds_fetched_at"],
            "high_deviation": bool(deviation is not None and deviation > 0.15),
            "contradicts_favorite": contradicts_favorite,
        })

        if include_offers and binary_market:
            offers = []
            for offer in _available_prices(event, feed_key, feed_name, point):
                offered_bet = {**bet, "best_odds": offer["price"]}
                offered_price = price_bet(offered_bet, pricing_prediction, prob)
                offers.append({**candidates[-1], **offered_price, "best_odds": offer["price"],
                               "bookmaker": offer["bookmaker"], "bookmaker_key": offer["bookmaker_key"],
                               "quote_last_update": offer["last_update"],
                               "selection_market_reference": market_evidence(event, feed_key, feed_name, point,
                                   now=quote_as_of, exclude_book=offer["bookmaker_key"])})
            candidates[-1]["bookmaker_offers"] = offers

    h2h_outcomes = [
        ("home_win", home_outcome_name, prediction["probability_home_win"]),
        ("draw", "Draw", prediction["probability_draw"]),
        ("away_win", away_outcome_name, prediction["probability_away_win"]),
    ]
    from src.bet_selection import market_consensus
    for label, outcome_name, prob in h2h_outcomes:
        market_prob = market_consensus(event, "h2h", outcome_name, now=quote_as_of)
        best = _best_price(event, "h2h", outcome_name)
        if best:
            _add_candidate("1X2", label, outcome_name if label != "draw" else None, prob, best, market_prob)

    sp = prediction.get("score_prediction", {})
    ou = sp.get("betting_markets", {}).get("over_under", [])
    if sp.get("score_matrix") is not None:
        offered_lines = {o["point"] for book in event.get("bookmakers", [])
                         for m in book.get("markets", []) if m.get("key") == "totals"
                         for o in m.get("outcomes", []) if isinstance(o.get("point"), (int, float))}
        ou = [{"line": line, "over": 0.5, "under": 0.5} for line in sorted(offered_lines)]
    for o in ou:
        line = float(o.get("line", 0))
        over_prob = o.get("over")
        under_prob = o.get("under", (1 - over_prob) if over_prob is not None else None)

        for side, prob in (("Over", over_prob), ("Under", under_prob)):
            if prob is None:
                continue
            market_prob = market_consensus(event, "totals", side, line, now=quote_as_of)
            best = _best_price(event, "totals", side, point=line)
            if best:
                _add_candidate(f"Over/Under {line}", side, None, prob, best, market_prob)

    home_xg = sp.get("home_xg")
    away_xg = sp.get("away_xg")
    if home_xg is not None and away_xg is not None:
        spread_points = {(o["name"], o["point"]) for book in event.get("bookmakers", [])
                         for m in book.get("markets", []) if m.get("key") == "spreads"
                         for o in m.get("outcomes", []) if isinstance(o.get("point"), (int, float))}
        for team_name, point in sorted(spread_points):
            market_prob = market_consensus(event, "spreads", team_name, point, now=quote_as_of)
            # price_bet derives probabilities from H/D/A or the complete matrix.
            prob = 0.0
            best = _best_price(event, "spreads", team_name, point=point)
            if best:
                sign = "+" if point > 0 else ""
                _add_candidate(f"Handicap {sign}{point}", "handicap", team_name, prob, best, market_prob)

    candidates.sort(key=lambda c: c["expected_value"], reverse=True)

    # "Verdächtig" = zu hoher Vorteil (Modellfehler) oder starke Modell-Markt-
    # Abweichung. Solche Wetten zeigen wir an, aber nicht als sichere Empfehlung.
    for c in candidates:
        c["suspicious"] = bool(
            c["expected_value"] > REALISTIC_EV_CEILING
            or c["high_deviation"]
            or c.get("contradicts_favorite")
        )

    # Grün = positiver Vorteil. Sortiert nach Kelly-Einsatz (verlässliche zuerst),
    # saubere vor verdächtigen.
    greens = sorted(
        [c for c in candidates if c["expected_value"] > 0],
        key=lambda c: (not c["suspicious"], c["kelly_stake_pct"]),
        reverse=True,
    )
    # Ein paar rote (negativer Vorteil) als Kontrast - die "am wenigsten schlechten".
    reds = sorted(
        [c for c in candidates if c["expected_value"] <= 0],
        key=lambda c: c["expected_value"],
        reverse=True,
    )[:3]

    # A "clean" bet with a tiny Kelly stake (e.g. 0.2%) technically has a
    # positive edge, but it's not a real tip - the system's own sizing says
    # "barely worth a bet". Below this threshold, treat it the same as "no
    # value pick" rather than presenting a near-zero edge as a confident
    # recommendation (see Brazil vs Japan: a +2.8%/0.2%-stake Draw was shown
    # as the headline pick while +30%+ edges sat filtered out as suspicious).
    MIN_KELLY_FOR_RECOMMENDATION = 1.0

    clean = [c for c in greens if not c["suspicious"] and c["kelly_stake_pct_raw"] >= MIN_KELLY_FOR_RECOMMENDATION and c["quote_fresh"]]
    if clean:
        recommendation, rec_warning = clean[0], False
    elif greens:
        recommendation, rec_warning = greens[0], True
    else:
        recommendation, rec_warning = None, False

    # The model's own favorite (highest H/D/A probability), shown as a 1X2
    # candidate regardless of whether it clears the value-edge bar - so the
    # "most likely outcome" is never hidden just because the market already
    # prices it fairly. Clearly labeled as "no proven edge" wherever it's used.
    model_favorite = next(
        (c for c in candidates if c["market"] == "1X2" and c["outcome"] == predicted_winner), None
    )

    market_favorite = max((c for c in candidates if c["market"] == "1X2" and c.get("quote_fresh") and c.get("market_probability") is not None),
                          key=lambda c: c["market_probability"], default=None)
    safest_pick = max((c for c in candidates if c.get("quote_fresh") and c["best_odds"] <= 1.5),
                      key=lambda c: c["probability"], default=None)
    for extra in (market_favorite, model_favorite, safest_pick):
        if extra and extra["expected_value"] <= 0 and extra not in reds:
            reds.append(extra)

    return {
        **context,
        "final_refresh_status": event.get("final_refresh_status", "complete" if context["odds_stage"] == "final" else "not_due"),
        "market_favorite": market_favorite,
        "safest_pick": safest_pick,
        "pricing_exclusions": pricing_exclusions,
        "home_team": event["home_team"],
        "away_team": event["away_team"],
        "commence_time": event.get("commence_time"),
        "odds_found": True,
        "event_id": event.get("id"),
        "sport_key": event.get("sport_key"),
        "recommendation": recommendation,
        "recommendation_warning": rec_warning,
        "model_favorite": model_favorite,
        "green_bets": greens,
        "red_bets": reds,
        "bets": candidates,
    }


def _call_gemini_agent_pick(
    prediction: dict, value_bets: dict, home_team: str, away_team: str,
    previous_eval: Optional[dict] = None,
) -> Optional[dict]:
    """Research without model numbers or a preferred tip; retain sourced claims.

    Previous output is used only to label revisions after the independent
    request, not to anchor the next prompt. Claims are not auto-verified.
    """
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    from src.bet_research import research_prompt, capture_evidence
    candidates = value_bets.get("bets") or []
    if not candidates:
        return None
    model_rec = value_bets.get("model_favorite")
    prompt = research_prompt(value_bets, home_team, away_team)

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = response.text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None
        source_urls = []
        for candidate in getattr(response, "candidates", []) or []:
            grounding = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(grounding, "grounding_chunks", []) or []:
                uri = getattr(getattr(chunk, "web", None), "uri", None)
                if uri:
                    source_urls.append(uri)
        evidence = capture_evidence(parsed, source_urls)
    except Exception:
        return None

    pick = None
    if parsed.get("pick_market"):
        for c in candidates:
            outcome_label = c.get("team") or c["outcome"]
            if c["market"] == parsed["pick_market"] and outcome_label == parsed.get("pick_outcome"):
                pick = c
                break

    # Whether the agent "agrees with the top bet" is a plain fact (does its pick
    # match our system's top recommendation) - compute it ourselves rather than
    # trust the model to self-report it, since that's strictly more reliable.
    agrees_with_model = bool(
        pick is not None and model_rec is not None
        and pick["market"] == model_rec["market"]
        and pick["outcome"] == model_rec["outcome"]
        and pick.get("team") == model_rec.get("team")
    )

    # Same idea as agrees_with_model: whether the pick changed from the prior
    # check is a plain fact, computed here rather than self-reported - so the
    # UI can show "kept" vs "revised" reliably even if the model's own wording
    # is inconsistent.
    revised_from_previous = None
    if previous_eval is not None:
        prev_pick = previous_eval.get("pick")
        revised_from_previous = not (
            (pick is None and prev_pick is None)
            or (
                pick is not None and prev_pick is not None
                and pick["market"] == prev_pick["market"]
                and pick["outcome"] == prev_pick["outcome"]
                and pick.get("team") == prev_pick.get("team")
            )
        )

    research = parsed.get("research") or {}
    return {
        "pick": pick,
        "research_version": "unanchored_club_v1",
        "evidence": evidence,
        "agrees_with_model": agrees_with_model,
        "revised_from_previous": revised_from_previous,
        "bet_headline": parsed.get("bet_headline") or "",
        "bet_reasoning": parsed.get("bet_reasoning") or "",
        "bet_points": [p for p in (parsed.get("bet_points") or []) if p],
        "research": {
            "lineups_injuries": research.get("lineups_injuries") or "",
            "form": research.get("form") or "",
            "table_situation": research.get("table_situation") or "",
            "other": research.get("other") or "",
        },
    }


_agent_picks_refresh_in_progress = False


# The Odds API returns every upcoming fixture it has lines for, several days
# out - but "Next Games" on the site only shows the current matchday slate
# (today's evening kickoffs through the early hours of the next morning).
# Limiting the agent to that same near-term window keeps each daily refresh
# to a handful of matches instead of the full multi-day odds list.
AGENT_EVAL_WINDOW_HOURS = 15


def _refresh_agent_picks(odds: list[dict]) -> None:
    """Compute one Gemini pick per match in today's matchday window, once per day.

    Runs in a background thread - even a handful of sequential Gemini calls is
    ~30s each, which must never block the request that happens to trigger it.
    The cache simply stays empty/stale until the background pass finishes;
    callers already handle agent_eval being None.
    """
    global _agent_picks_cache, _agent_picks_cache_date, _agent_picks_refresh_in_progress
    today = datetime.now(timezone.utc).date().isoformat()
    if _agent_picks_cache_date == today or _agent_picks_refresh_in_progress:
        return

    _agent_picks_refresh_in_progress = True

    def _eval_one(data):
        home, away = data["home_team"], data["away_team"]
        vb = _compute_value_bets(data, odds, home, away)
        if not vb.get("odds_found") or vb.get("in_play"):
            return None
        commence = vb.get("commence_time")
        if commence:
            try:
                kickoff = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                hours_away = (kickoff - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours_away > AGENT_EVAL_WINDOW_HOURS:
                    return None
            except ValueError:
                pass
        if vb.get("odds_stage") == "final":
            return None
        agent = _call_gemini_agent_pick(data, vb, home, away)
        if agent is None:
            return None
        return _agent_key(vb), agent

    def _run():
        global _agent_picks_cache, _agent_picks_cache_date, _agent_picks_refresh_in_progress
        picks: dict[tuple[str, str], dict] = {}
        try:
            # Each Gemini call (with search grounding) takes ~30s; a few
            # concurrent workers keep the daily refresh to ~1-2 minutes
            # instead of 8+ minutes run sequentially, without spiking rate
            # limits the way full parallelism would.
            with ThreadPoolExecutor(max_workers=4) as pool:
                for result in pool.map(_eval_one, list(_get_prediction_index().values())):
                    if result is not None:
                        key, agent = result
                        picks[key] = agent
            _agent_picks_cache = picks
            _agent_picks_cache_date = today
        finally:
            _agent_picks_refresh_in_progress = False

    threading.Thread(target=_run, daemon=True).start()


def _agent_key(vb):
    return (vb.get("sport_key"), vb.get("event_id"), vb.get("commence_time"),
            _norm_team(vb.get("home_team", "")), _norm_team(vb.get("away_team", "")))


def _get_agent_pick(vb) -> Optional[dict]:
    from src.bet_selection import same_bet
    cached = _agent_picks_cache.get(_agent_key(vb))
    if not cached:
        return None
    pick = next((b for b in vb.get("bets", []) if same_bet(b, cached.get("pick"))), None)
    return {**cached, "pick": pick, "pick_unavailable": bool(cached.get("pick") and pick is None)}


def _same_bet(a: Optional[dict], b: Optional[dict]) -> bool:
    if a is None or b is None:
        return False
    return a["market"] == b["market"] and a["outcome"] == b["outcome"] and a.get("team") == b.get("team")


def _combine_recommendation(vb: dict, agent_eval: Optional[dict]) -> dict:
    from src.bet_selection import combine
    return combine(vb, agent_eval)


# One independent research refresh during the final hour for each event.
# The earlier opinion is retained only for revision comparison, not the prompt.
_agent_prekickoff_done: set[tuple[str, str]] = set()
_agent_prekickoff_in_progress: set[tuple[str, str]] = set()
PREKICKOFF_WINDOW_HOURS = 1


def _maybe_prekickoff_refresh(odds: list[dict]) -> None:
    for data in _get_prediction_index().values():
        home, away = data["home_team"], data["away_team"]
        try:
            vb = _compute_value_bets(data, odds, home, away)
        except Exception:
            continue
        if not vb.get("odds_found") or vb.get("in_play"):
            continue
        if vb.get("odds_stage") != "final":
            continue
        key = _agent_key(vb)
        if key in _agent_prekickoff_done or key in _agent_prekickoff_in_progress:
            continue
        commence = vb.get("commence_time")
        if not commence:
            continue
        try:
            kickoff = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            hours_away = (kickoff - datetime.now(timezone.utc)).total_seconds() / 3600
        except ValueError:
            continue
        if not (0 <= hours_away <= PREKICKOFF_WINDOW_HOURS):
            continue

        _agent_prekickoff_in_progress.add(key)
        previous_eval = _agent_picks_cache.get(key)

        def _run(data=data, vb=vb, home=home, away=away, key=key, previous_eval=previous_eval):
            try:
                agent = _call_gemini_agent_pick(data, vb, home, away, previous_eval=previous_eval)
                if agent is not None:
                    _agent_picks_cache[key] = agent
            finally:
                _agent_prekickoff_done.add(key)
                _agent_prekickoff_in_progress.discard(key)

        threading.Thread(target=_run, daemon=True).start()


_prediction_index: dict[tuple[str, str], dict] = {}
_prediction_index_ts: float = 0
_PREDICTION_INDEX_TTL = 300  # seconds - cache files only change when we (re)generate predictions


def _get_prediction_index() -> dict[tuple[str, str], dict]:
    global _prediction_index, _prediction_index_ts
    now = time.time()
    if not _prediction_index or (now - _prediction_index_ts) > _PREDICTION_INDEX_TTL:
        index = {}
        if PREDICTIONS_CACHE_DIR.exists():
            for path in PREDICTIONS_CACHE_DIR.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                key = (_norm_team(data.get("home_team", "")), _norm_team(data.get("away_team", "")))
                index[key] = data
        _prediction_index = index
        _prediction_index_ts = now
    return _prediction_index


def _find_cached_prediction(home_team: str, away_team: str) -> Optional[dict]:
    return _get_prediction_index().get((_norm_team(home_team), _norm_team(away_team)))


@app.get("/value-bets")
def value_bets(home_team: str, away_team: str):
    try:
        odds = _get_odds()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Odds API unavailable: {exc}")
    try:
        # Most matches already have a cached prediction (generated ahead of the
        # matchday) - reuse it instead of re-running the model. Only fall back
        # to a live prediction for matches nobody has generated yet.
        prediction = _find_cached_prediction(home_team, away_team)
        if prediction is None:
            prediction = _predictor_for(home_team, away_team).predict_match(home_team, away_team)
        result = _compute_value_bets(prediction, odds, home_team, away_team)
        _refresh_agent_picks(odds)
        _maybe_prekickoff_refresh(odds)
        agent_eval = _get_agent_pick(result)
        result["agent_eval"] = agent_eval
        result["combined"] = _combine_recommendation(result, agent_eval)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/best-bets")
def best_bets():
    """Matchday overview: all clean top recommendations for upcoming matches.

    Iterates cached predictions, keeps only matches that currently have odds
    (i.e. upcoming) and a clean recommendation (positive edge, no warning).

    Reuses each match's already-computed prediction from the cache instead of
    re-running the model - re-predicting all ~70 cached matches on every
    request was the main cause of the site feeling slow/unresponsive.
    """
    try:
        odds = _get_odds()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Odds API unavailable: {exc}")

    _refresh_agent_picks(odds)
    _maybe_prekickoff_refresh(odds)

    out = []
    for data in _get_prediction_index().values():
        try:
            home, away = data["home_team"], data["away_team"]
            vb = _compute_value_bets(data, odds, home, away)
        except Exception:
            continue
        if not vb.get("odds_found") or vb.get("in_play"):
            continue
        agent_eval = _get_agent_pick(vb)
        combined = _combine_recommendation(vb, agent_eval)
        if combined["consensus_pick"] is None:
            continue
        out.append({
            "home_team": vb["home_team"],
            "away_team": vb["away_team"],
            "commence_time": vb.get("commence_time"),
            "recommendation": vb.get("recommendation"),
            "agent_eval": agent_eval,
            "combined": combined,
        })

    out.sort(key=lambda x: x.get("commence_time") or "")
    return {"best_bets": out}


@app.get("/combo-ticket")
def combo_ticket(competition: Optional[str] = None, max_legs: int = 4):
    """Experimental same-book, same-day combos of individually qualified legs.

    Quotes are repriced per bookmaker, including that offer's independent
    reference set. Ticket ranking uses stressed expected log growth and
    explicitly assumes independence between distinct fixtures.
    """
    from src.combo_ticket import combo_report, MAX_LEGS

    try:
        odds = _get_odds()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Odds API unavailable: {exc}")

    max_legs = max(2, min(int(max_legs), MAX_LEGS))
    pairs = []
    for data in _get_prediction_index().values():
        try:
            vb = _compute_value_bets(data, odds, data["home_team"], data["away_team"], include_offers=True)
        except Exception:
            continue
        if competition and vb.get("sport_key") != competition:
            continue
        pairs.append((data, vb))

    report = combo_report(pairs, max_legs=max_legs)
    report["competition"] = competition

    return report


@app.get("/all-bets")
def all_bets():
    """Every upcoming match with odds, full breakdown - for honest logging.

    Unlike /best-bets (which only surfaces the curated "clean" top picks for
    the UI), this returns EVERY match that currently has odds, with the exact
    same data the frontend's SmartBetCard renders for it: the top
    recommendation (even if flagged as a warning), every green and red
    candidate bet, and the agent evaluation. Nothing is filtered out here -
    the point is to let scripts/log_bets.py capture the full picture for every
    match while the odds still exist, since they disappear once a match ends.
    """
    try:
        odds = _get_odds()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Odds API unavailable: {exc}")

    _refresh_agent_picks(odds)
    _maybe_prekickoff_refresh(odds)

    out = []
    for data in _get_prediction_index().values():
        try:
            home, away = data["home_team"], data["away_team"]
            vb = _compute_value_bets(data, odds, home, away)
        except Exception:
            continue
        if not vb.get("odds_found") or vb.get("in_play"):
            continue
        agent_eval = _get_agent_pick(vb)
        out.append({
            "event_id": vb.get("event_id"),
            "sport_key": vb.get("sport_key"),
            "selection_policy": "robust_game_pick_v1",
            **{k: vb.get(k) for k in ("odds_fetched_at", "odds_stage", "snapshot_valid_until", "snapshot_valid", "calculated_at", "quote_basis", "final_refresh_status")},
            "market_favorite": vb.get("market_favorite"),
            "pricing_exclusions": vb.get("pricing_exclusions", []),
            "prediction": data,
            "bets": vb.get("bets", []),
            "safest_pick": vb.get("safest_pick"),
            "home_team": vb["home_team"],
            "away_team": vb["away_team"],
            "commence_time": vb.get("commence_time"),
            "recommendation": vb.get("recommendation"),
            "recommendation_warning": vb.get("recommendation_warning"),
            "model_favorite": vb.get("model_favorite"),
            "green_bets": vb.get("green_bets", []),
            "red_bets": vb.get("red_bets", []),
            "agent_eval": agent_eval,
            "combined": _combine_recommendation(vb, agent_eval),
        })

    out.sort(key=lambda x: x.get("commence_time") or "")
    return {"all_bets": out}


FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

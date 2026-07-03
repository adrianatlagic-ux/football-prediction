from __future__ import annotations

import json
import os
import re
import statistics
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
from scipy.stats import poisson

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor

MODEL_PATH = Path(os.getenv("MODEL_PATH", "model.joblib"))
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


def _get_predictor() -> FootballPredictor:
    global _predictor
    if _predictor is None:
        _predictor = FootballPredictor(model_path=MODEL_PATH if MODEL_PATH.exists() else None)
        if not _predictor._trained:
            raise HTTPException(status_code=503, detail="Modell nicht trainiert. POST /train aufrufen.")
    return _predictor


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
    predictor = _get_predictor()
    try:
        result = predictor.predict_match(
            req.home_team,
            req.away_team,
            neutral=req.neutral,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return PredictResponse(
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
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/"
        "scoreboard?dates=20260611-20260719&limit=100"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
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
# The Odds API charges (regions x markets) credits per call. We request 1
# region x 3 markets = 3 credits/call. Refreshing once per day keeps usage
# at ~3 credits/day = ~90/month, far inside the 500/month free quota no
# matter how much traffic the site gets.
#
# Refresh is anchored to a fixed clock time (15:00 UTC = 17:00 CEST) rather
# than a rolling 24h window, so it's predictable for everyone regardless of
# when they happen to load the site. 13:00 UTC (15:00 German summer time)
# sits well before the evening kickoff slot (~18:00 UTC / 20:00 German time) -
# early enough that this snapshot is a genuine "early" baseline odds can still
# move away from before the pre-kickoff re-check, rather than catching them
# only an hour or two apart.
ODDS_REFRESH_HOUR_UTC = 13
_odds_cache: list[dict] = []
_odds_cache_date: str | None = None  # UTC date (YYYY-MM-DD) of the last successful fetch

# Snapshot of each candidate bet's odds taken the first time it's seen each
# day (i.e. at the ODDS_REFRESH_HOUR_UTC refresh) - the baseline the
# pre-kickoff re-check later compares against to measure market movement.
_odds_baseline: dict[tuple[str, str], dict[tuple, float]] = {}
_odds_baseline_date: str | None = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Agent picks are computed once per match per day, anchored to the same clock
# time as the odds refresh - one Gemini call per match that has odds that day,
# not per request. Keeps volume identical to (and as predictable as) the odds.
_agent_picks_cache: dict[tuple[str, str], dict] = {}
_agent_picks_cache_date: str | None = None

# Vorteile über dieser Grenze sind praktisch immer ein Modellfehler, kein echter
# Value - sie werden nicht als Empfehlung ausgesprochen. Tiefer = konservativer.
REALISTIC_EV_CEILING = 0.30

# How much of our own model we keep when sizing a bet; the rest is pulled from
# the devig'd market price. 1.0 = trust the model fully (old behaviour), 0.0 =
# just follow the market (no value bet would ever appear). Set below 1.0
# because the model is overconfident vs the market - see _add_candidate and
# scripts/evaluate_model.py. Experimental knob, not a tuned value.
MODEL_MARKET_BLEND = 0.5
# Over/Under (the Poisson goals model) is our weakest market: across the user's
# real placed Tipico bets it went 2W/4L for -45% ROI, while 1X2 was +44%. So we
# trust the goals model even less - keep only a small slice of it and lean
# harder on the market for totals. Still experimental (can't be precisely tuned
# until enough O/U bets finish and get logged in full format).
MODEL_MARKET_BLEND_TOTALS = 0.3


def _fetch_odds() -> list[dict]:
    if not ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="ODDS_API_KEY ist nicht konfiguriert.")
    url = (
        "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/"
        f"?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals,spreads&oddsFormat=decimal"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())


def _get_odds() -> list[dict]:
    global _odds_cache, _odds_cache_date
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    due_for_refresh = now.hour >= ODDS_REFRESH_HOUR_UTC and _odds_cache_date != today
    if not _odds_cache or due_for_refresh:
        try:
            _odds_cache = _fetch_odds()
            _odds_cache_date = today
        except Exception:
            if not _odds_cache:
                raise
    return _odds_cache


def _fetch_event_odds(event_id: str) -> Optional[dict]:
    """Single-event odds refetch for the pre-kickoff movement check - much
    cheaper than a full slate refresh (see The Odds API's per-event pricing)
    since we only need one match, not the whole matchday."""
    if not ODDS_API_KEY:
        return None
    url = (
        f"https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/events/{event_id}/odds"
        f"?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals,spreads&oddsFormat=decimal"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# The Odds API uses different team names than our fixtures for a few
# countries. Keyed/valued by the post-normalization (letters-only) form.
_ODDS_TEAM_ALIASES = {
    "usa": "unitedstates",
}


def _norm_team(name: str) -> str:
    # The Odds API writes "Bosnia & Herzegovina", we write "...and...".
    # Strip "and"/"&" as a standalone joiner so both normalize the same way,
    # without cutting "and" out of names like "Iceland".
    name = re.sub(r"\band\b", " ", name.lower())
    name = name.replace("&", " ")
    norm = re.sub(r"[^a-z]", "", name)
    return _ODDS_TEAM_ALIASES.get(norm, norm)


def _find_odds_match(odds: list[dict], home_team: str, away_team: str) -> Optional[dict]:
    h, a = _norm_team(home_team), _norm_team(away_team)
    for event in odds:
        eh, ea = _norm_team(event.get("home_team", "")), _norm_team(event.get("away_team", ""))
        if (h in eh or eh in h) and (a in ea or ea in a):
            return event
        if (h in ea or ea in h) and (a in eh or eh in a):
            return event
    return None


def _best_price(event: dict, market_key: str, outcome_name: str, point: Optional[float] = None) -> Optional[dict]:
    best = None
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != market_key:
                continue
            for outcome in market.get("outcomes", []):
                if outcome.get("name") != outcome_name:
                    continue
                if point is not None and outcome.get("point") != point:
                    continue
                if best is None or outcome["price"] > best["price"]:
                    best = {"price": outcome["price"], "bookmaker": bm.get("title")}
    return best


def _market_prices(event: dict, market_key: str, outcome_name: str, point: Optional[float] = None) -> list[float]:
    prices = []
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != market_key:
                continue
            for outcome in market.get("outcomes", []):
                if outcome.get("name") != outcome_name:
                    continue
                if point is not None and outcome.get("point") != point:
                    continue
                prices.append(outcome["price"])
    return prices


def _devig(raw_implied_probs: list[float]) -> list[float]:
    """Remove bookmaker overround so probabilities sum to 1 (true market view)."""
    total = sum(raw_implied_probs)
    if total <= 0:
        return raw_implied_probs
    return [p / total for p in raw_implied_probs]


def _kelly_quarter_stake(prob: float, odds: float) -> float:
    """Quarter-Kelly recommended stake as a fraction of bankroll (0..1)."""
    b = odds - 1
    if b <= 0:
        return 0.0
    full_kelly = (prob * odds - 1) / b
    return max(0.0, min(full_kelly, 1.0)) / 4


def _common_spread_points(event: dict) -> dict[str, float]:
    """Most frequently quoted handicap line per team name across bookmakers."""
    counts: dict[tuple[str, float], int] = {}
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "spreads":
                continue
            for outcome in market.get("outcomes", []):
                key = (outcome.get("name"), outcome.get("point"))
                counts[key] = counts.get(key, 0) + 1
    best_per_team: dict[str, tuple[float, int]] = {}
    for (name, point), count in counts.items():
        if name not in best_per_team or count > best_per_team[name][1]:
            best_per_team[name] = (point, count)
    return {name: point for name, (point, _) in best_per_team.items()}


def _handicap_cover_prob(home_xg: float, away_xg: float, team_is_home: bool, point: float, max_goals: int = 8) -> float:
    """P(team's goal margin + handicap point > 0) from independent Poisson goals.

    Only used for genuine Asian handicap lines (e.g. -1.5, +2.0) where there's
    no simpler equivalent already computed. Double Chance (+0.5) and Draw No
    Bet (0.0) are handled separately using the model's own H/D/A probabilities
    directly - see the call site - since those need no extra computation and
    must stay numerically consistent with the rest of the prediction.
    """
    total = 0.0
    for h in range(max_goals + 1):
        ph = poisson.pmf(h, home_xg)
        for a in range(max_goals + 1):
            margin = (h - a) if team_is_home else (a - h)
            if margin + point > 0:
                total += ph * poisson.pmf(a, away_xg)
    return total


@app.get("/odds")
def get_odds():
    try:
        return {"events": _get_odds()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Odds API unavailable: {exc}")


def _candidate_id(c: dict) -> tuple:
    return (c["market"], c["outcome"], c.get("team"))


def _record_odds_baseline(key: tuple[str, str], candidates: list[dict]) -> None:
    """Store each candidate's odds the first time they're seen each day (i.e.
    at the ODDS_REFRESH_HOUR_UTC refresh) - the early baseline the pre-kickoff
    re-check later compares against to measure market movement. Never
    overwritten again the same day, so later (e.g. pre-kickoff) calls compare
    against the same fixed early snapshot rather than a constantly moving one.
    """
    global _odds_baseline, _odds_baseline_date
    today = datetime.now(timezone.utc).date().isoformat()
    if _odds_baseline_date != today:
        _odds_baseline = {}
        _odds_baseline_date = today
    if key not in _odds_baseline:
        _odds_baseline[key] = {_candidate_id(c): c["best_odds"] for c in candidates}


def _odds_movement_pct(key: tuple[str, str], candidate: dict) -> Optional[float]:
    """How many percentage points a candidate's implied probability has moved
    in our favor since the day's early baseline (positive = market has moved
    toward agreeing with this pick since we first saw it; negative = away
    from it). None if no baseline odds were recorded for this candidate."""
    baseline = _odds_baseline.get(key)
    if not baseline:
        return None
    baseline_odds = baseline.get(_candidate_id(candidate))
    if not baseline_odds or not candidate.get("best_odds"):
        return None
    baseline_prob = 1 / baseline_odds
    current_prob = 1 / candidate["best_odds"]
    return round((current_prob - baseline_prob) * 100, 2)


def _compute_value_bets(prediction: dict, odds: list[dict], home_team: str, away_team: str) -> dict:
    event = _find_odds_match(odds, home_team, away_team)
    if event is None:
        return {"home_team": home_team, "away_team": away_team, "odds_found": False, "bets": []}

    # Once a match has kicked off, bookmaker odds become live/in-play odds that
    # react to the score and game state - but our model's probabilities are
    # fixed pre-match estimates that don't know any of that. Comparing the two
    # would produce meaningless "edges", so we don't recommend in-play matches.
    commence = event.get("commence_time")
    if commence:
        try:
            kickoff = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= kickoff:
                return {
                    "home_team": event["home_team"],
                    "away_team": event["away_team"],
                    "commence_time": commence,
                    "odds_found": True,
                    "in_play": True,
                    "recommendation": None,
                    "recommendation_warning": False,
                    "green_bets": [],
                    "red_bets": [],
                    "bets": [],
                }
        except ValueError:
            pass

    swapped = _norm_team(event.get("home_team", "")) != _norm_team(home_team) and (
        _norm_team(event.get("home_team", "")) in _norm_team(away_team)
        or _norm_team(away_team) in _norm_team(event.get("home_team", ""))
    )

    candidates = []

    home_outcome_name = event["away_team"] if swapped else event["home_team"]
    away_outcome_name = event["home_team"] if swapped else event["away_team"]

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

    def _add_candidate(market, outcome, team, prob, best, market_prob):
        raw_prob = float(prob)
        market_prob = float(market_prob) if market_prob is not None else None
        # Calibration shrinkage: our model is measurably overconfident vs the
        # market (scripts/evaluate_model.py - it rated bets 60% that won 50%,
        # and the market's Brier score beat ours). So we don't trust the
        # model's disagreement with the market at face value: the probability
        # that actually drives EV/Kelly is blended toward the devig'd market
        # price. MODEL_MARKET_BLEND = how much of our own model we keep; the
        # rest is the market. This shrinks phantom "value" that was really just
        # model overconfidence. It is an experiment, not a tuned value - we
        # can't fit it on ~9 graded bets - so it lives as one obvious knob.
        blend = MODEL_MARKET_BLEND_TOTALS if market.startswith("Over/Under") else MODEL_MARKET_BLEND
        if market_prob is not None:
            prob = blend * raw_prob + (1 - blend) * market_prob
        else:
            prob = raw_prob
        ev = prob * best["price"] - 1
        deviation = abs(prob - market_prob) if market_prob is not None else None
        # "Double Chance" (Handicap +0.5) is just "this team or draw" - if we
        # confidently favor the OTHER team to win outright, backing the
        # opponent's double chance contradicts our own headline just like a
        # contrary 1X2 bet would (see Ecuador/Germany: we favored Germany at
        # 57%, but "Ecuador or Draw" was recommended - same inconsistency).
        #
        # Over/Under candidates below 60% probability are already filtered out
        # before they ever reach here (see the over/under loop below), so
        # there's no separate "contradicts the model's own lean" check needed
        # for that market anymore.
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
            "model_probability_raw": round(raw_prob, 4),
            "market_probability": round(market_prob, 4) if market_prob is not None else None,
            "best_odds": best["price"],
            "bookmaker": best["bookmaker"],
            "expected_value": round(ev, 4),
            "kelly_stake_pct": round(_kelly_quarter_stake(prob, best["price"]) * 100, 1),
            "high_deviation": bool(deviation is not None and deviation > 0.15),
            "contradicts_favorite": contradicts_favorite,
        })

    h2h_outcomes = [
        ("home_win", home_outcome_name, prediction["probability_home_win"]),
        ("draw", "Draw", prediction["probability_draw"]),
        ("away_win", away_outcome_name, prediction["probability_away_win"]),
    ]
    h2h_median_implied = []
    for _, outcome_name, _ in h2h_outcomes:
        prices = _market_prices(event, "h2h", outcome_name)
        h2h_median_implied.append(1 / statistics.median(prices) if prices else 0.0)
    h2h_market_probs = _devig(h2h_median_implied) if sum(h2h_median_implied) > 0 else [None] * 3

    for (label, outcome_name, prob), market_prob in zip(h2h_outcomes, h2h_market_probs):
        best = _best_price(event, "h2h", outcome_name)
        if best:
            _add_candidate("1X2", label, outcome_name if label != "draw" else None, prob, best, market_prob)

    sp = prediction.get("score_prediction", {})
    ou = sp.get("betting_markets", {}).get("over_under", [])
    for o in ou:
        line = float(o.get("line", 0))
        over_prob = o.get("over")
        under_prob = o.get("under", (1 - over_prob) if over_prob is not None else None)

        over_prices = _market_prices(event, "totals", "Over", point=line)
        under_prices = _market_prices(event, "totals", "Under", point=line)
        over_implied = 1 / statistics.median(over_prices) if over_prices else 0.0
        under_implied = 1 / statistics.median(under_prices) if under_prices else 0.0
        if over_implied + under_implied > 0:
            market_over, market_under = _devig([over_implied, under_implied])
        else:
            market_over = market_under = None

        for side, prob, market_prob in (("Over", over_prob, market_over), ("Under", under_prob, market_under)):
            if prob is None:
                continue
            # A calibration check across all completed WC2026 matches found that
            # when the model only weakly favors one side of an Over/Under line
            # (50-60% probability), it's actually right LESS than half the time
            # (~42%) - worse than a coin flip. That's not a real edge, just
            # noise dressed up as a lean. Anything below 60% - including the
            # outright minority side (under 50%, which is even less
            # justified to back) - isn't reliable enough to offer as a
            # candidate bet at all.
            if prob < 0.60:
                continue
            best = _best_price(event, "totals", side, point=line)
            if best:
                _add_candidate(f"Over/Under {line}", side, None, prob, best, market_prob)

    home_xg = sp.get("home_xg")
    away_xg = sp.get("away_xg")
    if home_xg is not None and away_xg is not None:
        spread_points = _common_spread_points(event)
        for team_name, point in spread_points.items():
            # Handicap -0.5 = "win by 1+" = a plain win, identical to the 1X2
            # win bet. Skip it to avoid listing the same outcome twice.
            if point == -0.5:
                continue
            team_is_home = _norm_team(team_name) == _norm_team(home_outcome_name)
            opponent_name = away_outcome_name if team_is_home else home_outcome_name
            opponent_point = spread_points.get(opponent_name)

            team_prices = _market_prices(event, "spreads", team_name, point=point)
            opp_prices = _market_prices(event, "spreads", opponent_name, point=opponent_point) if opponent_point is not None else []
            team_implied = 1 / statistics.median(team_prices) if team_prices else 0.0
            opp_implied = 1 / statistics.median(opp_prices) if opp_prices else 0.0
            market_prob = _devig([team_implied, opp_implied])[0] if (team_implied + opp_implied) > 0 else None

            team_win_prob = prediction["probability_home_win"] if team_is_home else prediction["probability_away_win"]
            if point == 0.5:
                # Double Chance ("team or draw") = P(win) + P(draw) - plain
                # addition of mutually exclusive outcomes, using the model's
                # own headline probabilities directly rather than a separate
                # Poisson recomputation that could (and did) disagree with them.
                prob = team_win_prob + prediction["probability_draw"]
            elif point == 0.0:
                # Draw No Bet = P(team wins outright); a draw pushes (handled
                # in grading), so the draw probability isn't part of this.
                prob = team_win_prob
            else:
                prob = _handicap_cover_prob(home_xg, away_xg, team_is_home, point)
            best = _best_price(event, "spreads", team_name, point=point)
            if best:
                sign = "+" if point > 0 else ""
                _add_candidate(f"Handicap {sign}{point}", "handicap", team_name, prob, best, market_prob)

    candidates.sort(key=lambda c: c["expected_value"], reverse=True)

    match_key = (_norm_team(home_team), _norm_team(away_team))
    _record_odds_baseline(match_key, candidates)

    # Filled in only once the pre-kickoff single-event refetch has run for
    # this match (see _maybe_prekickoff_refresh) - None for every candidate
    # the rest of the day, when there's nothing fresher than the baseline
    # itself to compare against.
    pct_by_candidate = _movement_pct_cache.get(match_key, {})
    for c in candidates:
        c["movement_pct"] = pct_by_candidate.get(_candidate_id(c))

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

    clean = [c for c in greens if not c["suspicious"] and c["kelly_stake_pct"] >= MIN_KELLY_FOR_RECOMMENDATION]
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

    # 1X2 is a coin-flip in plenty of matches (e.g. Belgium vs Senegal: 43%
    # favorite) while the SAME model is confident elsewhere (e.g. 76% on Over
    # 1.5) - showing the weak 1X2 number as "the model's favorite" buries the
    # stronger, more useful signal the model actually has for that match.
    # Thresholds are grounded in scripts/evaluate_model.py's calibration
    # buckets across all logged bets: below ~60% the model's stated
    # probability is unreliable in every market (hit rate 14-29%), at 60%+ it
    # becomes trustworthy (hit rate 33-100%, mostly good). WEAK_1X2 sits just
    # under that line, STRONG_ALTERNATIVE just over it, so we only override
    # 1X2 when it's genuinely a toss-up AND the alternative has demonstrably
    # reliable footing - not simply because DC/O-U mathematically score higher
    # (they always do; see the earlier Double Chance discussion).
    WEAK_1X2_THRESHOLD = 0.55
    STRONG_ALTERNATIVE_THRESHOLD = 0.65
    if model_favorite is not None and model_favorite["probability"] < WEAK_1X2_THRESHOLD:
        alternative = max(
            (c for c in candidates if c["market"] != "1X2" and c["probability"] >= STRONG_ALTERNATIVE_THRESHOLD),
            key=lambda c: c["probability"],
            default=None,
        )
        if alternative is not None:
            model_favorite = alternative

    # The model's highest-probability bet across ALL market types (1X2, Double
    # Chance, Over/Under, Handicap), restricted to odds the bookmaker also
    # prices as near-certain. The odds filter is what keeps this honest:
    # comparing raw probabilities across markets is unfair since Double Chance
    # is mathematically >= its corresponding 1X2 outcome (win+draw >= win
    # alone) and would otherwise always win. Requiring low odds means the
    # market independently agrees it's safe, not just that it covers more
    # outcomes.
    SAFEST_PICK_MAX_ODDS = 1.50
    safest_candidates = [c for c in candidates if c["best_odds"] is not None and c["best_odds"] <= SAFEST_PICK_MAX_ODDS]
    safest_pick = max(safest_candidates, key=lambda c: c["probability"], default=None)

    # model_favorite and safest_pick must always be visible in the table, even
    # with negative edge - "reds" above is capped to the 3 least-bad
    # candidates, which can silently cut one of them if its edge is worse
    # than that. Without this, the ◆/🛡 marker would point at a row that
    # simply isn't shown.
    # The MARKET's favorite: the 1X2 outcome the bookmaker prices shortest
    # (highest implied probability). This is "swim with the market" - back the
    # team the market itself makes favorite to win outright. In a backtest over
    # the logged, finished matches this simple pick hit ~82% (9W/2L) - better
    # than our value bets (56%) or any cleverer cross-market pick (73%), which
    # kept wandering into the losing Double Chance market. Small sample, will
    # regress toward ~65-70% long-run, but it's the single best-performing and
    # simplest signal we have, so it leads the headline. Not a value bet: at
    # short odds the edge is usually flat/negative, which is expected and fine.
    market_favorite = min(
        (c for c in candidates if c["market"] == "1X2"),
        key=lambda c: c["best_odds"],
        default=None,
    )

    for extra in (model_favorite, safest_pick, market_favorite):
        if extra is None or extra["expected_value"] > 0:
            continue
        if not any(_candidate_id(c) == _candidate_id(extra) for c in reds):
            reds.append(extra)
    reds.sort(key=lambda c: c["expected_value"], reverse=True)

    return {
        "home_team": event["home_team"],
        "away_team": event["away_team"],
        "commence_time": event.get("commence_time"),
        "odds_found": True,
        "recommendation": recommendation,
        "recommendation_warning": rec_warning,
        "model_favorite": model_favorite,
        "market_favorite": market_favorite,
        "safest_pick": safest_pick,
        "green_bets": greens,
        "red_bets": reds,
        "bets": candidates,
    }


def _call_gemini_agent_pick(
    prediction: dict, value_bets: dict, home_team: str, away_team: str,
    previous_eval: Optional[dict] = None,
) -> Optional[dict]:
    """Ask Gemini (with Google Search grounding) to research current context our
    stats model can't see, and separately evaluate the candidate bets against it.

    Returns two distinct, structured pieces - kept deliberately apart and kept
    short, since a wall of prose isn't scannable in a UI card:
    - "research": short factual bullets by category (lineups/injuries, form,
      table situation, other) - shown in the main analysis section,
      independent of any betting angle. Empty string for categories with
      nothing worth reporting.
    - "bet_headline" / "bet_reasoning" / "bet_points": the betting verdict -
      a plain-language pick label, one sentence of reasoning, and a couple of
      short supporting bullets - shown only in the Smart Bet section.

    If `previous_eval` is given (an earlier agent_eval for this same match),
    the agent is told what it concluded before and asked to explicitly confirm
    or revise it with a reason - rather than re-researching from a blank slate
    and potentially flip-flopping for no real reason. This is what lets us
    safely re-check a match later (e.g. closer to kickoff) without the earlier,
    possibly-better take silently vanishing without explanation.

    Returns None if the call fails (caller treats that as "no agent opinion",
    not block the rest of the response).
    """
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    candidates = (value_bets.get("green_bets") or []) + (value_bets.get("red_bets") or [])
    if not candidates:
        return None

    # Deliberately give the agent ONLY the market + outcome + odds for each
    # candidate - NOT our model's per-bet probability or expected value, and
    # NOT which bet our system already recommends. Revealing those anchored the
    # agent into rubber-stamping our pick, so its "agreement" carried no
    # independent information (see Netherlands-Morocco: agent just echoed the
    # lone green bet). With only the raw market on the table it has to form its
    # own view, which is the entire point of having a second opinion.
    cand_lines = "\n".join(
        f"- market={c['market']}, outcome={c.get('team') or c['outcome']}, odds={c['best_odds']}"
        for c in candidates
    )

    previous_block = ""
    if previous_eval and previous_eval.get("bet_headline"):
        prev_pick = previous_eval.get("pick")
        prev_pick_desc = (
            f"market={prev_pick['market']}, outcome={prev_pick.get('team') or prev_pick['outcome']}"
            if prev_pick else "none"
        )
        previous_block = f"""

YOUR EARLIER ASSESSMENT of this same match (from an earlier check today): \
pick="{previous_eval['bet_headline']}" ({prev_pick_desc}), reasoning="{previous_eval.get('bet_reasoning', '')}"

You are being asked again now, closer to kickoff, with a chance to search for newer information. \
Do NOT change your pick just to seem thorough or different - only revise it if you find a CONCRETE, \
NEW fact (e.g. a confirmed lineup change, injury, or news) that genuinely changes the picture. If \
nothing material has changed, keep the same pick and say so explicitly in bet_reasoning."""

    prompt = f"""You are researching an upcoming World Cup 2026 match: {home_team} vs {away_team}.

For reference only, our statistical model's headline probabilities: Home win \
{prediction['probability_home_win']:.0%}, Draw {prediction['probability_draw']:.0%}, \
Away win {prediction['probability_away_win']:.0%}. Treat these as one input to weigh \
against your own research - NOT as the answer to agree with.

The bets available to pick from (market and current odds only - decide for yourself \
which, if any, is worth backing):
{cand_lines}{previous_block}

STEP 1 - RESEARCH (use Google Search). Our stats model only sees historical results, so dig up CURRENT \
context across as many of these angles as you can actually find information on - don't limit yourself \
to just one or two:
- Confirmed/expected lineups, key injuries or suspensions (incl. accumulated yellow cards)
- Recent form (last 2-3 matches, goals for/against, performance trend)
- Group table situation: what does each team need from this result, is it a dead rubber, must-win, or \
already decided?
- Squad fatigue / travel / rest days since the last match, weather/pitch conditions if notable
- Coach or player quotes/interviews about tactics, motivation, or team news
- Head-to-head history or tactical matchup notes if genuinely relevant
- Any other concrete, current fact you find that could matter

STEP 2 - BETTING VERDICT. Based on YOUR research plus the odds, decide which ONE bet from the list is \
the best one to actually back - or none, if nothing looks good. Form this view independently; do not \
assume the model's most-likely outcome is the right bet. Then write bet_reasoning as exactly one \
sentence explaining why you landed on that pick (or why none of them are worth backing - e.g. too \
unpredictable, no real edge, the odds don't justify it).

Keep everything SHORT - this renders in a small card, not an article. Respond with ONLY raw JSON, no \
markdown formatting, no code fences, exactly this shape - everything in English:
{{"research": {{"lineups_injuries": "<one short sentence, or empty string if nothing found>", \
"form": "<one short sentence, or empty string>", "table_situation": "<one short sentence, or empty \
string>", "other": "<one short sentence on anything else notable, or empty string>"}}, \
"pick_market": "<one of the market strings above, or null>", "pick_outcome": "<matching outcome \
string, or null>", "bet_headline": "<2-5 words naming the pick in plain language, e.g. 'Over 2.5 \
goals' or 'Croatia to win' - or 'No good bet' if pick is null>", "bet_reasoning": "<exactly ONE \
sentence with your verdict>", "bet_points": ["<short supporting fact, max 8 words>", "<short \
supporting fact, max 8 words>"]}}"""

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
    except Exception:
        return None

    pick = None
    if parsed.get("pick_market"):
        for c in candidates:
            outcome_label = c.get("team") or c["outcome"]
            if c["market"] == parsed["pick_market"] and outcome_label == parsed.get("pick_outcome"):
                pick = c
                break

    # Whether the agent's INDEPENDENT pick happens to match the model's
    # most-likely outcome - the meaningful "do our two independent sources
    # agree" comparison (consistent with _combine_recommendation). Compared
    # against the model favorite, not the value rec, and computed ourselves
    # rather than trusting the agent to self-report it.
    model_fav = value_bets.get("model_favorite")
    agrees_with_model = bool(
        pick is not None and model_fav is not None
        and pick["market"] == model_fav["market"]
        and pick["outcome"] == model_fav["outcome"]
        and pick.get("team") == model_fav.get("team")
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
        agent = _call_gemini_agent_pick(data, vb, home, away)
        if agent is None:
            return None
        return (_norm_team(home), _norm_team(away)), agent

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


def _get_agent_pick(home_team: str, away_team: str) -> Optional[dict]:
    return _agent_picks_cache.get((_norm_team(home_team), _norm_team(away_team)))


def _same_bet(a: Optional[dict], b: Optional[dict]) -> bool:
    if a is None or b is None:
        return False
    return a["market"] == b["market"] and a["outcome"] == b["outcome"] and a.get("team") == b.get("team")


def _combine_recommendation(vb: dict, agent_eval: Optional[dict]) -> dict:
    """Combine the genuinely INDEPENDENT opinions into one verdict.

    There are only two independent sources of opinion about which bet to make:
    - the statistical model (its most-likely outcome = model_favorite)
    - the AI research agent (its own researched pick)

    The "value pick" is NOT a third opinion: it's the SAME model number read
    through the market (model_prob x odds - 1 > 0), so counting it as another
    vote was double-counting the model and made agreement look stronger than it
    was (e.g. Netherlands-Morocco showed "3 signals agree" when it was really
    one model opinion the de-anchored agent then echoed). So value is treated
    as a *property* of the consensus bet (does it also beat the market?), not a
    vote. A real consensus = the model and the AI, two independent sources,
    landing on the same bet.
    """
    market_fav = vb.get("market_favorite")
    model_fav = vb.get("model_favorite")
    # Warninged recs (sub-threshold/thin) don't count as a real value pick.
    value_pick = vb.get("recommendation") if not vb.get("recommendation_warning") else None
    agent_pick = agent_eval.get("pick") if agent_eval else None

    # The market favorite ("swim with the market" - back the team the market
    # itself makes favorite) leads the headline: it's the best-performing and
    # simplest signal we have (~82% hit in backtest vs 56% for value bets). The
    # model and AI act as a confidence traffic light on it, not as competing
    # picks - the whole point is to stop being cleverer than the market.
    model_agrees = _same_bet(market_fav, model_fav)
    agent_agrees = _same_bet(market_fav, agent_pick)
    agreement_count = int(model_agrees) + int(agent_agrees)

    if market_fav is not None:
        consensus_pick = market_fav
        if model_agrees and agent_agrees:
            label = "Market favorite — our model and the AI both agree"
        elif model_agrees:
            label = "Market favorite — our model agrees"
        elif agent_agrees:
            label = "Market favorite — the AI agrees"
        else:
            label = "Market favorite — note: our model and the AI see it differently"
    else:
        consensus_pick = None
        label = "No clear market favorite for this match"

    # The movement ranking is display-only context. An earlier version let it
    # OVERRIDE the pick above in the final hour before kickoff - which meant
    # the best-tracked signal kept getting displaced by an unvalidated
    # experiment (e.g. Belgium-Senegal: a -8%-edge "Win Belgium" replaced the
    # pick purely because its odds had drifted). Never again: it informs, it
    # doesn't decide.
    movement_ranking = vb.get("movement_ranking")

    return {
        "market_favorite": market_fav,
        "model_favorite": model_fav,
        "value_pick": value_pick,
        "agent_pick": agent_pick,
        "consensus_pick": consensus_pick,
        "consensus_label": label,
        "model_agrees": model_agrees,
        "agent_agrees": agent_agrees,
        "agreement_count": agreement_count,
        "movement_ranking": movement_ranking,
    }


# A second per-match check, exactly in the hour before its own kickoff, so the
# agent can catch lineup/news that wasn't out yet at the early-afternoon pass. A first
# version of this silently overwrote the earlier pick with a fresh one and, in
# practice, sometimes made things worse with no way to tell which take to
# trust. Fixed by feeding the agent its own earlier pick as context (see
# `previous_eval` in _call_gemini_agent_pick) and explicitly telling it to
# keep that pick unless it finds a genuinely new, concrete fact - so this is a
# considered update, not a blind re-roll. Still strictly per-match: each match
# crosses its own "1h before kickoff" point at a different time, so only the
# one match currently in that window gets re-evaluated, never all of them.
_agent_prekickoff_done: set[tuple[str, str]] = set()
_agent_prekickoff_in_progress: set[tuple[str, str]] = set()
PREKICKOFF_WINDOW_HOURS = 1

# Each match's movement ranking, computed once at the pre-kickoff re-check
# (see _rank_by_movement) and reused by every request afterwards until the
# match kicks off - it's not recomputed per-request.
_movement_cache: dict[tuple[str, str], list[dict]] = {}
# Per-candidate movement (percentage points) from the same pre-kickoff
# refetch, keyed by candidate id - lets _compute_value_bets annotate every
# bet in the table (not just the 4 signals) without an extra API call.
_movement_pct_cache: dict[tuple[str, str], dict[tuple, float]] = {}
# The full value-bets result computed from the fresh single-event odds at the
# pre-kickoff refetch. Once this exists for a match, callers should serve it
# instead of recomputing from the stale once-a-day odds cache - odds (and so
# the recommended pick) can genuinely move in that last hour, and showing the
# headline pick from hours-old odds while the movement ranking below it
# already reflects fresher ones would be inconsistent.
_prekickoff_vb_cache: dict[tuple[str, str], dict] = {}


def _rank_by_movement(key: tuple[str, str], vb: dict, agent_eval: Optional[dict]) -> list[dict]:
    """Rank the four signals (model favorite, value pick, AI pick, safest
    pick) by how much the market has moved towards each of them since the
    day's early odds snapshot - the bet the market itself increasingly
    confirms ranks first, the one it's moving away from ranks last. Every
    signal that has a bet gets a rank, including unfavorable movers (they
    just rank low and show red in the UI)."""
    signals = [
        ("Model Favorite", vb.get("model_favorite")),
        ("Value Pick", vb.get("recommendation")),
        ("AI Pick", agent_eval.get("pick") if agent_eval else None),
        ("Safest Pick", vb.get("safest_pick")),
    ]
    ranked = [
        {"signal": label, "bet": bet, "movement_pct": _odds_movement_pct(key, bet)}
        for label, bet in signals
        if bet is not None
    ]
    ranked.sort(key=lambda r: r["movement_pct"] if r["movement_pct"] is not None else float("-inf"), reverse=True)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return ranked


def _maybe_prekickoff_refresh(odds: list[dict]) -> None:
    for data in _get_prediction_index().values():
        home, away = data["home_team"], data["away_team"]
        key = (_norm_team(home), _norm_team(away))
        if key in _agent_prekickoff_done or key in _agent_prekickoff_in_progress:
            continue
        try:
            vb = _compute_value_bets(data, odds, home, away)
        except Exception:
            continue
        if not vb.get("odds_found") or vb.get("in_play"):
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
        event = _find_odds_match(odds, home, away)
        event_id = event.get("id") if event else None

        def _run(data=data, vb=vb, home=home, away=away, key=key, previous_eval=previous_eval, event_id=event_id):
            try:
                # Single-event refetch right before the agent re-check, so the
                # movement ranking compares the day's early snapshot against
                # odds that are actually fresh at this point - not the same
                # daily-cached odds the rest of the day runs on.
                fresh_event = _fetch_event_odds(event_id) if event_id else None
                fresh_vb = _compute_value_bets(data, [fresh_event], home, away) if fresh_event else vb

                if fresh_event:
                    for c in fresh_vb.get("bets", []):
                        c["movement_pct"] = _odds_movement_pct(key, c)
                    _movement_pct_cache[key] = {_candidate_id(c): c["movement_pct"] for c in fresh_vb.get("bets", [])}
                    fresh_vb["odds_refreshed"] = True
                    _prekickoff_vb_cache[key] = fresh_vb

                agent = _call_gemini_agent_pick(data, fresh_vb, home, away, previous_eval=previous_eval)
                if agent is not None:
                    _agent_picks_cache[key] = agent

                _movement_cache[key] = _rank_by_movement(key, fresh_vb, agent or previous_eval)
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
            prediction = _get_predictor().predict_match(home_team, away_team)
        match_key = (_norm_team(home_team), _norm_team(away_team))
        # Within the pre-kickoff window, prefer the result already recomputed
        # from genuinely fresh odds over recomputing from the stale daily
        # cache - otherwise the headline pick/odds here could silently
        # disagree with the movement ranking shown right below it.
        result = _prekickoff_vb_cache.get(match_key) or _compute_value_bets(prediction, odds, home_team, away_team)
        _refresh_agent_picks(odds)
        _maybe_prekickoff_refresh(odds)
        agent_eval = _get_agent_pick(home_team, away_team)
        result["agent_eval"] = agent_eval
        result["movement_ranking"] = _movement_cache.get(match_key)
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
            match_key = (_norm_team(home), _norm_team(away))
            vb = _prekickoff_vb_cache.get(match_key) or _compute_value_bets(data, odds, home, away)
        except Exception:
            continue
        if not vb.get("odds_found") or vb.get("in_play"):
            continue
        agent_eval = _get_agent_pick(home, away)
        vb["movement_ranking"] = _movement_cache.get(match_key)
        combined = _combine_recommendation(vb, agent_eval)
        if combined["consensus_pick"] is None:
            continue
        out.append({
            "home_team": vb["home_team"],
            "away_team": vb["away_team"],
            "commence_time": vb.get("commence_time"),
            "recommendation": vb.get("recommendation"),
            "odds_refreshed": vb.get("odds_refreshed", False),
            "agent_eval": agent_eval,
            "combined": combined,
        })

    out.sort(key=lambda x: x.get("commence_time") or "")
    return {"best_bets": out}


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
            match_key = (_norm_team(home), _norm_team(away))
            cached = _prekickoff_vb_cache.get(match_key)
            fresh = _compute_value_bets(data, odds, home, away)
            # Prefer the fresh pre-kickoff recompute (with movement ranking) so
            # the log captures what the site actually showed near kickoff, not
            # just the early-afternoon snapshot. Otherwise the movement-ranked
            # Top Recommendation the user saw would never make it into the log.
            #
            # If the match has since gone in-play, `fresh` would report
            # in_play=True and get filtered below - but the movement ranking
            # was computed in the background (~30s Gemini call) and may not
            # have landed in the cache before kickoff crossed over. Falling
            # back to the cached pre-kickoff snapshot here means a match
            # doesn't vanish from the log mid-way through getting its ranking
            # just because kickoff happened in the gap between hourly log runs.
            vb = cached if (cached and fresh.get("in_play")) else fresh
        except Exception:
            continue
        if not vb.get("odds_found") or vb.get("in_play"):
            continue
        agent_eval = _get_agent_pick(home, away)
        vb["movement_ranking"] = _movement_cache.get(match_key)
        out.append({
            "home_team": vb["home_team"],
            "away_team": vb["away_team"],
            "commence_time": vb.get("commence_time"),
            "recommendation": vb.get("recommendation"),
            "recommendation_warning": vb.get("recommendation_warning"),
            "model_favorite": vb.get("model_favorite"),
            "market_favorite": vb.get("market_favorite"),
            "safest_pick": vb.get("safest_pick"),
            "odds_refreshed": vb.get("odds_refreshed", False),
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

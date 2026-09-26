from __future__ import annotations

import json
import math
import unicodedata
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.club_predictor import ClubFootballPredictor as FootballPredictor

from src.club_predictor import DEFAULT_MODEL_PATH as MODEL_PATH
from src import book_odds
from src.price_tip import build_price_tip, model_and_ai_view
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


# Writing a prediction replaces what every visitor then sees, so the endpoint
# needs to know who is calling. Setting PREDICTIONS_WRITE_TOKEN in the
# deployment turns the check on; leaving it unset keeps the old open
# behaviour, which is only safe on a local machine.
PREDICTIONS_WRITE_TOKEN = os.getenv("PREDICTIONS_WRITE_TOKEN", "")


@app.post("/predictions/{match_id}")
def save_prediction(match_id: str, payload: dict[str, Any],
                    x_prediction_token: str = Header(default="")):
    if PREDICTIONS_WRITE_TOKEN and not secrets.compare_digest(
            x_prediction_token, PREDICTIONS_WRITE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid prediction write token")
    PREDICTIONS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(match_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "match_id": match_id}


# ── Scheduled jobs (src/jobs.py), knocked on by .github/workflows/jobs.yml ──

def _require_job_token(token: str) -> None:
    # Jobs spend Apify credit and rewrite the cache, so unlike the prediction
    # upload they are refused outright when no token is configured.
    if not PREDICTIONS_WRITE_TOKEN or not secrets.compare_digest(token, PREDICTIONS_WRITE_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid job token")


def _start_job(name: str, work) -> dict:
    from src import jobs
    if jobs._lock.locked():
        return {"started": False, "reason": "another job is running"}

    def run():
        global _prediction_index_ts
        try:
            work()
        finally:
            _prediction_index_ts = 0     # the cache changed: re-read it
    requested_at = datetime.now(timezone.utc).isoformat()
    threading.Thread(target=run, daemon=True, name=f"job-{name}").start()
    # The workflow waits for a report started after this moment and fails on
    # its errors - a job that only started is not a job that worked.
    return {"started": True, "job": name, "requested_at": requested_at}


@app.post("/jobs/daily")
def job_daily(x_prediction_token: str = Header(default="")):
    _require_job_token(x_prediction_token)
    from src import jobs
    return _start_job("daily", lambda: jobs.run_daily(_get_predictor, _get_national_predictor, _get_odds))


@app.post("/jobs/hourly")
def job_hourly(x_prediction_token: str = Header(default="")):
    _require_job_token(x_prediction_token)
    from src import jobs
    return _start_job("hourly", lambda: jobs.run_hourly(_get_predictor, _get_national_predictor))


@app.get("/fixtures")
def fixtures():
    """The season's fixture lists, rebuilt by the daily job (src/fixtures.py)."""
    from src.fixtures import load_all
    return load_all()


@app.get("/jobs/status")
def job_status():
    from src import jobs
    out = {}
    for name in ("daily", "hourly"):
        try:
            out[name] = json.loads((jobs.REPORTS / f"last_{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out[name] = None
    return out


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
    "Bayern Munich": "Bayern Munich",
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Spurs": "Tottenham",
    "Paris Saint Germain": "Paris Saint-Germain",
    "Atletico Madrid": "Atlético Madrid",
}

_espn_cache: dict[str, Any] = {}
_espn_cache_ts: float = 0
_ESPN_TTL = 300  # seconds - each refresh reads ~130 ESPN day pages in parallel


def _espn_team(name: str) -> str:
    """ESPN's spelling -> the name our fixtures use.

    The country map above covers national teams. Club names go through the
    same canonicalisation the training data uses, so ESPN's "SC Paderborn 07"
    and our "SC Paderborn" describe one team instead of two - otherwise the
    finished-result card never finds its fixture and the match keeps showing
    a prediction after it has been played.
    """
    if name in _ESPN_NAME_MAP:
        return _ESPN_NAME_MAP[name]
    try:
        from scripts.build_club_training_data import _canon
        return _canon(name)
    except Exception:
        return name


_ESPN_LEAGUES = (("uefa.champions", "soccer_uefa_champs_league"),
                 ("ger.1", "soccer_germany_bundesliga"),
                 ("ger.2", "soccer_germany_bundesliga2"),
                 ("uefa.nations", "soccer_uefa_nations_league"))


def _fetch_espn_results() -> list[dict]:
    results = []
    errors = []
    for league, sport in _ESPN_LEAGUES:
        try:
            results.extend(_fetch_espn_league(league, sport))
        except Exception as exc:
            errors.append(exc)
    if not results and errors:
        raise errors[0]
    return results


def _espn_national_team(name: str) -> str:
    """ESPN's nation names mapped the way the national fixtures file spells them."""
    try:
        from scripts.fetch_national_results import team_name
        return team_name(name)
    except Exception:
        return name


def _headline_value(home: str, away: str, sport: str) -> float:
    """How much of a headline a result is: the weaker side's value, since a
    top game needs two strong teams. A side we hold no value for (Bodø/Glimt,
    Sabah) counts as a quarter of its opponent rather than zero, so Bayern's
    5:0 is not ranked below two anonymous clubs."""
    h, a = _team_value(home, sport), _team_value(away, sport)
    return min(h, a) if h and a else max(h, a) / 4


def _team_value(team: str, sport: str) -> float:
    """Squad market value, used only to rank which results are the headline ones."""
    try:
        if sport == "soccer_uefa_nations_league":
            from src.market_values import VALUES
        else:
            from src.club_market_values import MARKET_VALUES as VALUES
        return float(VALUES.get(team, 0))
    except Exception:
        return 0.0


# The bare scoreboard only returns ESPN's current window, so a match played
# a few days ago silently disappears and its card loses the real result.
# Date ranges are rejected (HTTP 400), single days are not, so the recent
# days are requested individually and merged.
# The last matchday played must keep its results on the page, and in the
# Champions League that can be four weeks back.
ESPN_RESULT_DAYS = 32


def _fetch_espn_league(league, sport) -> list[dict]:
    # Deliberately no User-Agent header. ESPN answers 403 to a spoofed browser
    # UA ("Mozilla/5.0") and 200 to Python's default one, so the header that
    # was meant to look harmless is what broke /real-results. The Odds API
    # calls below are unaffected and keep theirs.
    base = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
    today = datetime.now(timezone.utc).date()
    events, seen = [], set()
    urls = [f"{base}?limit=100"] + [
        f"{base}?limit=100&dates={(today - timedelta(days=d)).strftime('%Y%m%d')}"
        for d in range(ESPN_RESULT_DAYS + 1)
    ]
    def _get(url):
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                return json.loads(resp.read())
        except Exception:
            # One missing day must not drop the whole competition.
            return {}

    # Parallel, because the ticker needs each competition's last matchday and
    # a club competition's can lie almost two weeks back.
    with ThreadPoolExecutor(max_workers=8) as pool:
        payloads = list(pool.map(_get, urls))
    for payload in payloads:
        for event in payload.get("events", []):
            if event.get("id") not in seen:
                seen.add(event.get("id"))
                events.append(event)

    data = {"events": events}
    results = []
    for event in data.get("events", []):
        comp = event["competitions"][0]
        status = comp["status"]["type"]
        completed = status.get("completed", False)

        competitors = comp["competitors"]
        # ESPN: index 0 = home, index 1 = away
        home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        to_name = _espn_national_team if sport == "soccer_uefa_nations_league" else _espn_team
        home_team = to_name(home_c["team"]["displayName"])
        away_team = to_name(away_c["team"]["displayName"])

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
            "headline_value": _headline_value(home_team, away_team, sport),
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
from src.odds_schedule import DAILY_REFRESH_HOUR_UTC as ODDS_REFRESH_HOUR_UTC
_odds_cache: list[dict] = []
_odds_cache_date: str | None = None
_odds_cache_fetched_at = 0.0
_odds_daily_refresh_date = None
_final_odds_cache = {}
_final_odds_attempts = {}
_odds_refresh_lock = threading.Lock()
ODDS_CACHE_TTL_SECONDS = int(os.getenv("ODDS_CACHE_TTL_SECONDS", "0"))  # 0 retains daily quota policy

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Agent picks are cached per match indefinitely once computed (see
# _refresh_agent_picks) - never recomputed for a match that already has one.
_agent_picks_cache: dict[tuple[str, str], dict] = {}
# Throttles how often a background pass is even considered, independent of
# whether it finds anything to do - without this, every request would spawn a
# pass just to discover every remaining gap is a finished/too-far-out match,
# since those never get a cache entry to short-circuit on.
_agent_picks_last_check: float = 0.0
AGENT_PICKS_CHECK_COOLDOWN_SECONDS = 180

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


# Fetch every competition available in the frontend, including national teams.
# This list also allows the event-specific refresh in the final pre-match hour.
# From the 06:00 UTC read to midday the next day, so tomorrow's early
# kickoffs have bet-at-home prices before the next morning read.
ODDS_HORIZON_HOURS = 30
ODDS_SPORT_KEYS = [
    "soccer_uefa_champs_league",
    "soccer_germany_bundesliga",
    "soccer_uefa_nations_league",
]


def _fetch_odds() -> list[dict]:
    """The day's fixtures from the Odds API's free event list - no prices.

    Prices come from two other reads: bet-at-home's full market book right
    after this one (src/book_odds.daily_refresh), and Pinnacle once per match
    in its last hour (_fetch_event_odds), when the price tip is decided. The
    event list costs no credits, so the morning read spends nothing of the
    Odds API plan; each match then costs 3 credits, once.
    """
    if not ODDS_API_KEY:
        raise HTTPException(status_code=503, detail="ODDS_API_KEY ist nicht konfiguriert.")
    events: list[dict] = []
    last_error: Exception | None = None
    now = datetime.now(timezone.utc)
    window = (f"&commenceTimeFrom={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
              f"&commenceTimeTo={(now + timedelta(hours=ODDS_HORIZON_HOURS)).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    for sport_key in ODDS_SPORT_KEYS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events?apiKey={ODDS_API_KEY}{window}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                events.extend({**e, "bookmakers": e.get("bookmakers", [])} for e in json.loads(resp.read()))
        except Exception as exc:
            last_error = exc
    if not events and last_error is not None:
        raise last_error
    return events


def _fetch_event_odds(event):
    """Refresh only the event's own supported competition."""
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


# The day's odds snapshot, kept on disk. Every process start used to fetch
# all competitions again (9 credits of a 500-a-month plan); a restart on the
# same day now reuses the stored snapshot instead.
ODDS_SNAPSHOT_PATH = Path(os.getenv("ODDS_SNAPSHOT_PATH",
                                    Path(__file__).parent.parent / "data" / "odds_snapshot.json"))


def _load_odds_snapshot(now: datetime) -> Optional[tuple]:
    """(events, fetched_at, stage) from disk if it is today's, else None."""
    try:
        stored = json.loads(ODDS_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(stored["fetched_at"])
    except (OSError, ValueError, KeyError):
        return None
    if fetched.date() != now.date():
        return None
    # A snapshot from before the daily refresh hour does not stand in for it.
    if now.hour >= ODDS_REFRESH_HOUR_UTC and fetched.hour < ODDS_REFRESH_HOUR_UTC:
        return None
    return stored["events"], fetched, stored.get("stage", "daily")


def _save_odds_snapshot(events: list[dict], fetched: datetime, stage: str) -> None:
    try:
        ODDS_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ODDS_SNAPSHOT_PATH.write_text(json.dumps({"fetched_at": fetched.isoformat(), "stage": stage,
                                                  "events": events}), encoding="utf-8")
    except OSError:
        pass


def _refresh_book_daily(events: list[dict]) -> None:
    for sport in book_odds.LEAGUES:
        try:
            book_odds.daily_refresh(sport, [e for e in events if e.get("sport_key") == sport])
        except Exception:
            pass


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
        if not _odds_cache and not ttl_expired:
            stored = _load_odds_snapshot(now)
            if stored:
                events, fetched, stage = stored
                _odds_cache = [stamp_event(e, fetched, stage) for e in events]
                _odds_cache_date = fetched.date().isoformat()
                _odds_cache_fetched_at = fetched.timestamp()
                if stage == "daily":
                    _odds_daily_refresh_date = fetched.date().isoformat()
                due = now.hour >= ODDS_REFRESH_HOUR_UTC and _odds_daily_refresh_date != today
        if not _odds_cache or due or ttl_expired:
            try:
                events = _fetch_odds()
                fetched = datetime.now(timezone.utc)
                stage = "daily" if fetched.hour >= ODDS_REFRESH_HOUR_UTC else "initial"
                _save_odds_snapshot(events, fetched, stage)
                _odds_cache = [stamp_event(e, fetched, stage) for e in events]
                # bet-at-home's 1X2, read right after the snapshot so the two
                # line up for the bet table and the combo all day. Cheap (0.3
                # cents a match) and in the background: a scraper must not
                # hold up the odds every page is waiting for.
                threading.Thread(target=_refresh_book_daily, args=(list(_odds_cache),), daemon=True).start()
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


# The only bookmaker the user bets with. Its odds come from OddsPortal
# (src/book_odds.py) and are added to the Odds API event as one more book.
USER_BOOK_KEY = "betathome"


def _with_book_odds(event: dict) -> dict:
    """The event with bet-at-home added, when its odds match the snapshot.

    bet-at-home is only added if it was fetched within the quote-freshness
    window of the event's own odds snapshot, either side: a price from hours
    earlier set beside a fresh Pinnacle price would show gaps that no longer
    exist. The full market book has its own fetch time and is checked alone.
    """
    from src.price_tip import match_fixture
    from src.bet_selection import MAX_QUOTE_AGE_SECONDS
    from src.bet_audit import timestamp
    try:
        snapshot = timestamp(event["odds_fetched_at"])
        fixture = match_fixture(event, book_odds.load().get("fixtures", []))
    except Exception:
        return event
    if not fixture:
        return event

    def stamp(value):
        try:
            fetched = timestamp(value)
        except (TypeError, ValueError):
            return None
        if abs((snapshot - fetched).total_seconds()) > MAX_QUOTE_AGE_SECONDS:
            return None
        return min(fetched, snapshot).isoformat()

    home, away = event["home_team"], event["away_team"]
    markets = []
    h2h_time = stamp(fixture.get("fetched_at"))
    if h2h_time:
        o = fixture["odds"]
        markets.append({"key": "h2h", "last_update": h2h_time, "outcomes": [
            {"name": home, "price": o["home"]}, {"name": "Draw", "price": o["draw"]},
            {"name": away, "price": o["away"]}]})
    full = fixture.get("markets") or {}
    full_time = stamp(fixture.get("markets_fetched_at"))
    if full and full_time:
        if full.get("totals"):
            markets.append({"key": "totals", "last_update": full_time, "outcomes": [
                {"name": side.title(), "price": line[side], "point": line["point"]}
                for line in full["totals"] for side in ("over", "under") if line.get(side)]})
        if full.get("spreads"):
            markets.append({"key": "spreads", "last_update": full_time, "outcomes": [
                {"name": name, "price": line[side], "point": point}
                for line in full["spreads"]
                for side, name, point in (("home", home, line["point"] + 0.0), ("away", away, -line["point"] + 0.0))
                if line.get(side)]})
        if full.get("btts"):
            markets.append({"key": "btts", "last_update": full_time, "outcomes": [
                {"name": "Yes", "price": full["btts"]["yes"]}, {"name": "No", "price": full["btts"]["no"]}]})
    if not markets:
        return event
    books = [b for b in event.get("bookmakers", []) if b.get("key") != USER_BOOK_KEY]
    return {**event, "bookmakers": books + [{"key": USER_BOOK_KEY, "title": "bet-at-home",
                                             "last_update": h2h_time or full_time, "markets": markets}]}


def _user_price(event, market_key, outcome_name, point=None):
    """bet-at-home's price where it quotes this market, else the best other.

    Once bet-at-home's own book covers a market, a line only other bookmakers
    offer is dropped: it is a bet the user cannot place.
    """
    offers = _available_prices(event, market_key, outcome_name, point)
    covered = any(m.get("key") == market_key for b in event.get("bookmakers", [])
                  if b.get("key") == USER_BOOK_KEY for m in b.get("markets", []))
    if covered:
        return next((o for o in offers if o["bookmaker_key"] == USER_BOOK_KEY), None)
    return max(offers, key=lambda o: o["price"], default=None)


@app.get("/odds")
def get_odds():
    try:
        return {"events": _get_odds()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Odds API unavailable: {exc}")


def _candidate_id(c: dict) -> tuple:
    return (c["market"], c["outcome"], c.get("team"))


def _compute_value_bets(prediction: dict, odds: list[dict], home_team: str, away_team: str, include_offers=False) -> dict:
    event = _find_odds_match(odds, home_team, away_team)
    if event is None:
        return {"home_team": home_team, "away_team": away_team, "odds_found": False, "bets": []}
    if event.get("odds_fetched_at"):
        event = _with_book_odds(event)

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
        from src.bet_selection import price_bet, quote_is_fresh, market_evidence, payout_metrics
        from src.combo_ticket import binary_market
        # Only markets that settle win-or-lose are shown. A quarter line like
        # Over/Under 3.25 splits the stake across 3.0 and 3.5, so exactly three
        # goals refunds one half and wins the other - a result the display has
        # no honest way to call a win or a loss. Draw-no-bet and whole-goal
        # lines refund outright. The combo builder already excluded all three
        # for the same reason; leaving them in the single-bet list only offered
        # the reader a bet we could not describe.
        # Draw No Bet is the one exception, and only at bet-at-home: it is a
        # market the user can place there, and a draw returning the stake is
        # a result anyone can read.
        if not binary_market(market) and not (market == "Handicap 0.0"
                                              and best.get("bookmaker_key") == USER_BOOK_KEY):
            return
        bet = {"market": market, "outcome": outcome, "team": team, "best_odds": best["price"]}
        try:
            priced = price_bet(bet, pricing_prediction, prob)
        except (ValueError, KeyError, TypeError) as exc:
            pricing_exclusions.append({"market": market, "outcome": outcome, "reason": str(exc)})
            return
        raw_prob = priced["probability"]
        prob = raw_prob
        binary_market = market == "1X2" or (market.startswith(("Handicap ", "Over/Under ")) and float(market.split()[-1]) % 1 == 0.5)
        market_prob = float(market_prob) if market_prob is not None and binary_market else None
        # Shrink the model toward the market before anything is priced off it.
        # The model is measurably overconfident - it rated bets 60% that won
        # 50%, and the market's Brier score beat ours - so its disagreement
        # with the price is not taken at face value. This survived the merge
        # only by being re-applied here: it used to sit in the EV line, and
        # the stress-tested selector that also carried it no longer chooses
        # the displayed pick.
        #
        # Only binary markets are blended, which is where market_prob exists
        # at all: with no push mass the payouts are just win/lose, so the
        # blended probability can be re-priced without inventing a settlement.
        if market_prob is not None:
            blend = MODEL_MARKET_BLEND_TOTALS if market.startswith("Over/Under") else MODEL_MARKET_BLEND
            prob = blend * raw_prob + (1 - blend) * market_prob
            priced = payout_metrics([(best["price"] - 1, prob), (-1, 1 - prob)])
        ev = priced["expected_value"]
        feed_key = ("h2h" if market == "1X2" else "totals" if market.startswith("Over/Under")
                    else "btts" if market == "BTTS" else "spreads")
        feed_name = (team or "Draw") if feed_key == "h2h" else outcome if feed_key in ("totals", "btts") else team
        point = None if feed_key in ("h2h", "btts") else float(market.split()[-1])
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
            "model_probability_raw": round(raw_prob, 4),
            "market_probability": round(market_prob, 4) if market_prob is not None else None,
            "best_odds": best["price"],
            "bookmaker": best["bookmaker"],
            "bookmaker_key": best.get("bookmaker_key"),
            "selection_market_reference": reference,
            "quote_last_update": best.get("last_update"),
            "model_probability_raw": round(raw_prob, 4),
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
        best = _user_price(event, "h2h", outcome_name)
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
            best = _user_price(event, "totals", side, point=line)
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
            best = _user_price(event, "spreads", team_name, point=point)
            if best:
                sign = "+" if point > 0 else ""
                _add_candidate(f"Handicap {sign}{point}", "handicap", team_name, prob, best, market_prob)

    # Both teams to score: bet-at-home's book carries it, the Odds API feed
    # does not. price_bet reads it off the full score matrix.
    for side in ("Yes", "No"):
        best = _user_price(event, "btts", side)
        if best:
            _add_candidate("BTTS", side, None, 0.0, best, None)

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
    MODEL_FAVORITE_MIN_ODDS = 1.20
    STRONG_ALTERNATIVE_THRESHOLD = 0.65
    if model_favorite is not None and model_favorite["probability"] < WEAK_1X2_THRESHOLD:
        # Near-certain lines at odds like 1.02 (Under 6.5) clear the
        # probability bar trivially and say nothing; with bet-at-home's full
        # book listing every line they started winning this slot.
        alternative = max(
            (c for c in candidates if c["market"] != "1X2" and c["probability"] >= STRONG_ALTERNATIVE_THRESHOLD
             and c["best_odds"] >= MODEL_FAVORITE_MIN_ODDS),
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

    # The most likely bet by the MARKET's estimate, at a price still worth
    # taking. Separate from the price tip on purpose: the price tip answers
    # "where does bet-at-home pay too much", this one "what will most likely
    # land". It claims no edge. It replaces the model-based safest pick,
    # because the model has shown no advantage over the market, and the
    # odds floor keeps it off near-certainties like Under 6.5 at 1.02.
    LIKELY_MIN_ODDS, LIKELY_MAX_ODDS = 1.30, 2.00
    likely_pick = max(
        (c for c in candidates if c.get("market_probability") is not None
         and LIKELY_MIN_ODDS <= c["best_odds"] <= LIKELY_MAX_ODDS),
        key=lambda c: (c["market_probability"], c["best_odds"]),
        default=None,
    )

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

    for extra in (model_favorite, safest_pick, market_favorite, likely_pick):
        if extra is None or extra["expected_value"] > 0:
            continue
        if not any(_candidate_id(c) == _candidate_id(extra) for c in reds):
            reds.append(extra)
    reds.sort(key=lambda c: c["expected_value"], reverse=True)

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
        "market_favorite": market_favorite,
        "safest_pick": safest_pick,
        "likely_pick": likely_pick,
        "green_bets": greens,
        "red_bets": reds,
        "bets": candidates,
    }


# The prompt was written for the World Cup; the competition is now named.
_AGENT_COMPETITION_NAMES = {
    "soccer_uefa_champs_league": "UEFA Champions League",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_uefa_nations_league": "UEFA Nations League",
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

    competition = _AGENT_COMPETITION_NAMES.get(value_bets.get("sport_key"), "football")
    prompt = f"""You are researching an upcoming {competition} match: {home_team} vs {away_team}.

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
- Table situation: what does each team need from this result, is it a dead rubber, must-win, or \
already decided?
- Squad fatigue / travel / rest days since the last match, weather/pitch conditions if notable
- Coach or player quotes/interviews about tactics, motivation, or team news
- Head-to-head history or tactical matchup notes if genuinely relevant
- Any other concrete, current fact you find that could matter

STEP 2 - BETTING VERDICT. Based on YOUR research plus the odds, decide which ONE bet from the list is \
the best one to actually back - or none, if nothing looks good. Form this view independently; do not \
assume the model's most-likely outcome is the right bet. Then write bet_reasoning as exactly one \
sentence explaining why you landed on that pick (or why none of them are worth backing - e.g. too \
unpredictable, no real edge, the odds don't justify it). Wrap the 2-4 words/phrases in that sentence \
that most directly justify the pick (the actual stat or fact doing the work, e.g. "zero goals \
conceded", "erratic form", "unbeaten in 8") in double asterisks like **this** - not team names, not \
filler words, only the specific evidence a reader would want to see highlighted.

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
        if not isinstance(parsed, dict):
            return None
        # Which pages the search actually returned, kept for the audit log.
        source_urls = []
        for candidate in getattr(response, "candidates", []) or []:
            grounding = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(grounding, "grounding_chunks", []) or []:
                uri = getattr(getattr(chunk, "web", None), "uri", None)
                if uri:
                    source_urls.append(uri)
        from src.bet_research import capture_evidence
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
        "research_version": "claude_prompt_v1",
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
    """Compute a Gemini pick for every match that has newly entered the
    matchday window (AGENT_EVAL_WINDOW_HOURS) since it was last checked.

    Runs in a background thread - even a handful of sequential Gemini calls is
    ~30s each, which must never block the request that happens to trigger it.
    The cache simply stays empty/stale until the background pass finishes;
    callers already handle agent_eval being None.

    Tracked per-match (not once-per-day globally): a match whose kickoff is
    >15h away when the day's first pass runs would otherwise never get picked
    up again until the separate 1-hour pre-kickoff re-check - leaving it with
    no AI pick for most of the day even though it's well within the window by
    the afternoon. Re-checking on every call (cheap: only Gemini-calls matches
    not yet in the cache) fixes that gap.
    """
    global _agent_picks_cache, _agent_picks_refresh_in_progress, _agent_picks_last_check
    if _agent_picks_refresh_in_progress:
        return
    now = time.monotonic()
    if now - _agent_picks_last_check < AGENT_PICKS_CHECK_COOLDOWN_SECONDS:
        return
    _agent_picks_last_check = now
    # Predictions, not odds rows, are the unit the agent evaluates.  Take the
    # snapshot before starting the thread so a cache refresh cannot mutate the
    # iterable while workers are reading it.
    fixtures = list(_get_prediction_index().values())
    if not fixtures:
        return
    _agent_picks_refresh_in_progress = True

    def _eval_one(data):
        home, away = data["home_team"], data["away_team"]
        key = (_norm_team(home), _norm_team(away))
        if key in _agent_picks_cache:
            return None
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
        global _agent_picks_cache, _agent_picks_refresh_in_progress
        try:
            # Each Gemini call (with search grounding) takes ~30s; a few
            # concurrent workers keep the refresh to ~1-2 minutes instead of
            # 8+ minutes run sequentially, without spiking rate limits the
            # way full parallelism would.
            with ThreadPoolExecutor(max_workers=4) as pool:
                for result in pool.map(_eval_one, fixtures):
                    if result is not None:
                        key, agent = result
                        _agent_picks_cache[key] = agent
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

# The full value-bets result computed from the fresh single-event odds at the
# pre-kickoff refetch. Once this exists for a match, callers should serve it
# instead of recomputing from the stale once-a-day odds cache - odds (and so
# the recommended pick) can genuinely move in that last hour before kickoff.
_prekickoff_vb_cache: dict[tuple[str, str], dict] = {}
# The event behind that refresh. The price tip reads Pinnacle from it: a gap to
# bet-at-home measured against the morning's Pinnacle price would be stale.
_prekickoff_event_cache: dict[tuple[str, str], dict] = {}


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
        event = _find_odds_match(odds, home, away)

        def _run(data=data, vb=vb, home=home, away=away, key=key, previous_eval=previous_eval, event=event):
            try:
                # Single-event refetch right before the agent re-check, so the
                # headline pick reflects odds that are actually fresh at this
                # point - not the same daily-cached odds the rest of the day
                # runs on.
                # Codex' fetcher takes the whole event: it refuses a refresh whose
                # identity changed, and it uses the event's own competition
                # instead of assuming the Champions League.
                try:
                    # _get_odds already read this match's final odds in the
                    # last hour; reading them again cost 3 more credits.
                    if event and event.get("odds_stage") == "final":
                        fresh_event = event
                    else:
                        fresh_event = _fetch_event_odds(event) if event else None
                except Exception:
                    fresh_event = None
                # bet-at-home must be as fresh as Pinnacle for the price tip and
                # for its odds to enter the table; refresh_if_due reads its full
                # market book once per match in this window.
                if event:
                    sport = event.get("sport_key")
                    book_odds.refresh_if_due(sport, [e for e in odds if e.get("sport_key") == sport])
                fresh_vb = _compute_value_bets(data, [fresh_event], home, away) if fresh_event else vb

                if fresh_event:
                    fresh_vb["odds_refreshed"] = True
                    # The pre-kickoff tracking key contains event metadata so
                    # an agent can distinguish rematches.  Public readers use
                    # the stable team-pair cache key, so store the refreshed
                    # pricing result under that key.
                    _prekickoff_vb_cache[_match_key(home, away)] = fresh_vb
                    _prekickoff_event_cache[_match_key(home, away)] = fresh_event

                agent = _call_gemini_agent_pick(data, fresh_vb, home, away, previous_eval=previous_eval)
                if agent is not None:
                    _agent_picks_cache[key] = agent
            finally:
                _agent_prekickoff_done.add(key)
                _agent_prekickoff_in_progress.discard(key)

        threading.Thread(target=_run, daemon=True).start()


def _price_tip_for(odds: list[dict], home: str, away: str, prediction: dict,
                   agent_eval: Optional[dict], candidates: Optional[list] = None) -> Optional[dict]:
    """bet-at-home against Pinnacle's fair price for one match (src/price_tip.py)."""
    event = _prekickoff_event_cache.get(_match_key(home, away)) or _find_odds_match(odds, home, away)
    if not event:
        return None
    try:
        tip = build_price_tip(event, book_odds.load())
    except Exception:
        return None
    if not tip.get("outcomes") and event.get("odds_stage") != "final":
        tip["reason"] = ("Pinnacle's price is read in the hour before kickoff. "
                         "The price tip is decided then.")
    tip.update(model_and_ai_view(tip.get("tip"), prediction, agent_eval, candidates,
                                 event.get("home_team"), event.get("away_team")))
    return tip


_prediction_index: dict[tuple[str, str], dict] = {}
_prediction_index_ts: float = 0
_PREDICTION_INDEX_TTL = 300  # seconds - cache files only change when we (re)generate predictions


def _match_key(home_team: str, away_team: str) -> tuple[str, str]:
    """The cache identity shared by prediction and pre-kickoff readers."""
    return (_norm_team(home_team), _norm_team(away_team))


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
                key = _match_key(data.get("home_team", ""), data.get("away_team", ""))
                index[key] = data
        _prediction_index = index
        _prediction_index_ts = now
    return _prediction_index


def _find_cached_prediction(home_team: str, away_team: str) -> Optional[dict]:
    return _get_prediction_index().get(_match_key(home_team, away_team))


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
        # Squad-adjusted predictions are written into the cache ahead of
        # kickoff by scripts/refresh_squad_predictions.py, not computed here:
        # a request should read a finished answer, not wait on a scraper and
        # a model fit. The flags below simply pass through whatever that job
        # recorded, so the page can say which numbers it is showing.
        for field in ("squad_adjusted", "squad_values_used", "squad_refreshed_at"):
            if prediction.get(field) is not None:
                result[field] = prediction[field]
        _refresh_agent_picks(odds)
        _maybe_prekickoff_refresh(odds)
        agent_eval = _get_agent_pick(result)
        result["agent_eval"] = agent_eval
        result["combined"] = _combine_recommendation(result, agent_eval)
        result["price_tip"] = _price_tip_for(odds, home_team, away_team, prediction, agent_eval,
                                             result.get("bets", []))
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
            match_key = _match_key(home, away)
            vb = _prekickoff_vb_cache.get(match_key) or _compute_value_bets(data, odds, home, away)
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
            "odds_refreshed": vb.get("odds_refreshed", False),
            "agent_eval": agent_eval,
            "combined": combined,
        })

    out.sort(key=lambda x: x.get("commence_time") or "")
    return {"best_bets": out}


@app.get("/combo-ticket")
def combo_ticket(competition: Optional[str] = None, max_legs: int = 4):
    """Same-book, same-day combos ranked by model/market win estimates.

    Uses the probability-based combo policy, without the stress selector.
    Quotes come from offered singles; fixture independence is assumed.
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

    # Only bet-at-home: the one bookmaker the user bets with.
    report = combo_report(pairs, max_legs=max_legs, book=USER_BOOK_KEY)
    report["competition"] = competition
    # The rule before 26 September, computed on the same matches for the log
    # only (scripts/log_combos.py); the page shows the market rule.
    legacy = combo_report(pairs, max_legs=max_legs, book=USER_BOOK_KEY, policy="legacy_v3")
    report["legacy_v3_days"] = [{"date": d["date"], "by_size": d["by_size"]} for d in legacy["days"]]

    from src.combo_ticket import price_tip_combos
    tips = []
    for data, vb in pairs:
        if not vb.get("odds_found") or vb.get("in_play"):
            continue
        tip = _price_tip_for(odds, data["home_team"], data["away_team"], data, None)
        if tip and tip.get("tip"):
            tips.append({"home_team": vb["home_team"], "away_team": vb["away_team"],
                         "commence_time": vb.get("commence_time"), "tip": tip["tip"]})
    report["price_tip_combos"] = price_tip_combos(tips)

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
            match_key = _match_key(home, away)
            cached = _prekickoff_vb_cache.get(match_key)
            fresh = _compute_value_bets(data, odds, home, away)
            # Prefer the fresh pre-kickoff recompute so the log captures what
            # the site actually showed near kickoff, not just the
            # early-afternoon snapshot.
            #
            # If the match has since gone in-play, `fresh` would report
            # in_play=True and get filtered below - but the pre-kickoff
            # re-check (agent call, ~30s) may not have landed in the cache
            # before kickoff crossed over. Falling back to the cached
            # pre-kickoff snapshot here means a match doesn't vanish from the
            # log just because kickoff happened in the gap between hourly
            # log runs.
            vb = cached if (cached and fresh.get("in_play")) else fresh
        except Exception:
            continue
        if not vb.get("odds_found") or vb.get("in_play"):
            continue
        agent_eval = _get_agent_pick(vb)
        out.append({
            "event_id": vb.get("event_id"),
            "sport_key": vb.get("sport_key"),
            # The displayed pick comes from _combine_signals - the market
            # favourite, with the model and the agent as a confidence light -
            # not from the historical stress-tested selector in src/game_pick.py.
            # Combo tickets also use their own probability-based policy.
            "selection_policy": "market_favorite_consensus_v1",
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
            "market_favorite": vb.get("market_favorite"),
            "safest_pick": vb.get("safest_pick"),
            "likely_pick": vb.get("likely_pick"),
            "odds_refreshed": vb.get("odds_refreshed", False),
            "green_bets": vb.get("green_bets", []),
            "red_bets": vb.get("red_bets", []),
            "agent_eval": agent_eval,
            "combined": _combine_recommendation(vb, agent_eval),
            # The price tip exactly as the page shows it, "no tip" included,
            # so the log can later say whether the strategy worked.
            "price_tip": _price_tip_for(odds, home, away, data, agent_eval, vb.get("bets", [])),
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

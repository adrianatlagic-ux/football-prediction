from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

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


FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

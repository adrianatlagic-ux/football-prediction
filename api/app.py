from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
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

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.predictor import FootballPredictor

MODEL_PATH = Path(os.getenv("MODEL_PATH", "model.joblib"))

app = FastAPI(
    title="Football Prediction API",
    description="Predict football match outcomes using machine learning.",
    version="1.0.0",
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
    return _predictor


class TrainResponse(BaseModel):
    accuracy: float
    log_loss: Optional[float] = None
    message: str


class PredictRequest(BaseModel):
    home_team: str
    away_team: str


class PredictResponse(BaseModel):
    home_team: str
    away_team: str
    prediction: str
    probability_home_win: float
    probability_draw: float
    probability_away_win: float


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/train", response_model=TrainResponse)
async def train(file: Optional[UploadFile] = File(None)):
    predictor = _get_predictor()
    data_path = None

    if file:
        tmp = Path("/tmp") / file.filename
        tmp.write_bytes(await file.read())
        data_path = tmp

    try:
        metrics = predictor.train(data_path=data_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    predictor.save(MODEL_PATH)
    return TrainResponse(
        accuracy=metrics["accuracy"],
        log_loss=metrics.get("log_loss"),
        message="Model trained and saved successfully.",
    )


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    predictor = _get_predictor()
    if not predictor._trained:
        raise HTTPException(status_code=400, detail="Model not trained. POST /train first.")
    try:
        result = predictor.predict_match(req.home_team, req.away_team)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return PredictResponse(**result)

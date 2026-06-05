#!/bin/bash

set -e

echo ""
echo "======================================================"
echo "  WM 2026 Predictor — Setup"
echo "======================================================"
echo ""

# Clone repo to Desktop
DEST="$HOME/Desktop/football-prediction"

if [ -d "$DEST" ]; then
  echo "📁 Ordner existiert bereits — aktualisiere..."
  git -C "$DEST" pull
else
  echo "📥 Klone Repository auf den Desktop..."
  git clone https://github.com/adrianatlagic-ux/football-prediction "$DEST"
fi

cd "$DEST"

echo ""
echo "======================================================"
echo "  Aktueller Projektstand"
echo "======================================================"
echo ""
echo "📦 Projektstruktur:"
echo ""
echo "  football-prediction/"
echo "  ├── src/"
echo "  │   ├── data_loader.py         — Lädt echte Länderspieldaten (49.355 Spiele)"
echo "  │   ├── feature_engineering.py — Form, H2H, Tore, FIFA-Ranking Features"
echo "  │   ├── fifa_rankings.py       — Offizielle FIFA Rankings Juni 2026"
echo "  │   ├── poisson_model.py       — Dixon-Coles Ergebnisvorhersage"
echo "  │   ├── predictor.py           — Haupt-Predictor (RF + XGBoost Ensemble)"
echo "  │   └── models/                — Random Forest, XGBoost, Ensemble"
echo "  ├── api/"
echo "  │   └── app.py                 — FastAPI Backend (REST API)"
echo "  ├── frontend/"
echo "  │   └── src/                   — React + Vite Frontend"
echo "  ├── scripts/"
echo "  │   ├── train.py               — Modell trainieren"
echo "  │   └── predict.py             — Einzelvorhersage CLI"
echo "  └── data/"
echo "      └── international_results.csv  — 49.355 echte Länderspiele seit 1872"
echo ""
echo "🤖 Modell:"
echo "  - Algorithmus  : Random Forest + XGBoost Ensemble"
echo "  - Trainingsdaten: 32.166 Länderspiele seit 1990"
echo "  - Genauigkeit  : 59.1%"
echo "  - Ergebnisse   : Dixon-Coles Poisson Modell (xG-basiert)"
echo "  - Features     : Form, H2H, Tore, Zu-Null, FIFA-Ranking"
echo ""
echo "🌍 WM 2026:"
echo "  - 60 Teams mit offiziellen FIFA Rankings (Juni 2026)"
echo "  - Alle Gruppenspiele im Datensatz vorhanden"
echo ""

# Python setup
echo "======================================================"
echo "  Python Dependencies installieren"
echo "======================================================"
echo ""

if ! command -v python3 &>/dev/null; then
  echo "❌ Python3 nicht gefunden. Bitte installiere Python 3.10+"
  exit 1
fi

pip3 install -r requirements.txt -q
pip3 install python-multipart scipy -q
echo "✅ Python Dependencies installiert"

# Train model
echo ""
echo "======================================================"
echo "  Modell trainieren (~3 Minuten)"
echo "======================================================"
echo ""
python3 scripts/train.py

# Frontend setup
echo ""
echo "======================================================"
echo "  Frontend Dependencies installieren"
echo "======================================================"
echo ""

if ! command -v node &>/dev/null; then
  echo "⚠️  Node.js nicht gefunden — Frontend wird übersprungen."
  echo "   Installiere Node.js von https://nodejs.org"
else
  cd frontend
  npm install -q
  npm run build -q
  cd ..
  echo "✅ Frontend gebaut"
fi

echo ""
echo "======================================================"
echo "  ✅ Setup abgeschlossen!"
echo "======================================================"
echo ""
echo "  Starten:"
echo ""
echo "  Terminal 1 — Backend:"
echo "    cd $DEST"
echo "    uvicorn api.app:app --reload"
echo ""
echo "  Terminal 2 — Frontend:"
echo "    cd $DEST/frontend"
echo "    npm run dev"
echo ""
echo "  Dann im Browser öffnen: http://localhost:5173"
echo ""
echo "  Oder direkt eine Vorhersage:"
echo "    python3 scripts/predict.py --home 'Germany' --away 'France'"
echo ""
echo "======================================================"

#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

if ! git lfs version >/dev/null 2>&1; then
  echo "Git LFS fehlt. Bitte zuerst git-lfs installieren."
  exit 1
fi
git lfs install --local
git lfs pull

if [ ! -x .venv/bin/python ]; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ erforderlich; PYTHON_BIN setzen"'
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info >= (3, 11), "Die .venv braucht Python 3.11+"'
.venv/bin/python -m pip install -r requirements-local.txt
.venv/bin/python scripts/verify_models.py

(cd frontend && npm ci && npm run build)
echo "GoalIQ ist eingerichtet."
echo "Backend: ./start_api.sh"
echo "Frontend: cd frontend && npm run dev"

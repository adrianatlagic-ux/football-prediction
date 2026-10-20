#!/bin/bash
set -e
cd "$(cd "$(dirname "$0")" && pwd)"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
fi
exec python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload

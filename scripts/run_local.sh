#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PORT="${PORT:-8000}"
MODE="${1:-serve}"

if [[ "$MODE" == "dev" ]]; then
  echo "Starting HalalLens in dev mode (FastAPI on :$PORT + Vite on :5173)..."
  (
    cd "$BACKEND_DIR"
    uvicorn app.main:app --reload --host 0.0.0.0 --port "$PORT"
  ) &
  BACK_PID=$!

  (
    cd "$FRONTEND_DIR"
    npm run dev -- --host 0.0.0.0
  ) &
  FRONT_PID=$!

  trap 'kill $BACK_PID $FRONT_PID 2>/dev/null || true' EXIT INT TERM
  wait
else
  if [[ ! -d "$FRONTEND_DIR/dist" ]]; then
    echo "Building frontend bundle..."
    (cd "$FRONTEND_DIR" && npm install && npm run build)
  fi
  echo "Starting HalalLens unified server on http://localhost:$PORT ..."
  cd "$BACKEND_DIR"
  exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi

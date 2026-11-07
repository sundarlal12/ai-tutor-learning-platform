#!/usr/bin/env bash
# Start all 5 services locally (no Docker). Reads .env if present. Logs in .run/*.log
set -euo pipefail
cd "$(dirname "$0")/.."; ROOT=$PWD
mkdir -p .run
[ -f .env ] && set -a && . ./.env && set +a
export VERIFIER_URL=${VERIFIER_URL:-http://127.0.0.1:8002}
export VOICE_URL=${VOICE_URL:-http://127.0.0.1:8003}
export GENERATOR_URL=${GENERATOR_URL:-http://127.0.0.1:8001}
export PUBLIC_BASE_URL=${PUBLIC_BASE_URL:-${VOICE_PUBLIC_URL:-http://127.0.0.1:8003}}
export KNOWLEDGE_DIR=${KNOWLEDGE_DIR:-$PWD/knowledge}
export SAMPLE_DIR=${SAMPLE_DIR:-$PWD/sample}
export SEED_DIR=${SEED_DIR:-$PWD/sample/bundles}
export DATA_DIR=${DATA_DIR:-$PWD/.run/data}
export MEDIA_DIR=${MEDIA_DIR:-$PWD/.run/media}
mkdir -p "$DATA_DIR" "$MEDIA_DIR"
start() { # name port
  (cd "services/$1" && nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$2" >"$ROOT/.run/$1.log" 2>&1 & echo $! >"$ROOT/.run/$1.pid")
  echo "started $1 on :$2"
}
start verifier 8002; start voice 8003; start generator 8001; start doubt 8004; start gateway 8000
sleep 3
for p in 8000 8001 8002 8003 8004; do curl -s -o /dev/null -w "port $p health: %{http_code}\n" http://127.0.0.1:$p/health || true; done
echo "Gateway: http://127.0.0.1:8000/v1/questions   (stop with scripts/dev_down.sh)"

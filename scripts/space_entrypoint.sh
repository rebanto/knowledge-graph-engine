#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/app}"
CHROMA_DIR="${CHROMA_PERSIST_DIR:-/data/chroma}"
BACKUP_INTERVAL_SECONDS="${CHROMA_BACKUP_INTERVAL_SECONDS:-86400}"

export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379}"
export CHROMA_HOST="${CHROMA_HOST:-127.0.0.1}"
export CHROMA_PORT="${CHROMA_PORT:-8001}"
export CHROMA_PERSIST_DIR="$CHROMA_DIR"
export CHROMA_BACKUP_PATH="${CHROMA_BACKUP_PATH:-$CHROMA_DIR}"
export STATIC_DIR="${STATIC_DIR:-$APP_DIR/frontend_dist}"
export USE_SHARDING="${USE_SHARDING:-false}"
export ENV="${ENV:-production}"

redis_pid=""
chroma_pid=""
worker_pid=""
api_pid=""
backup_pid=""

log() {
  printf '[space-entrypoint] %s\n' "$*"
}

stop_children() {
  set +e
  log "stopping child processes"
  for pid in "$api_pid" "$worker_pid" "$chroma_pid" "$redis_pid" "$backup_pid"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
    fi
  done
  wait 2>/dev/null
}

trap stop_children EXIT INT TERM

cd "$APP_DIR"
mkdir -p "$CHROMA_DIR"

log "restoring Chroma snapshot if configured"
python -m backend.core.chroma_backup restore --path "$CHROMA_DIR" || true

log "starting Redis on localhost"
redis-server \
  --bind 127.0.0.1 \
  --port 6379 \
  --save "" \
  --appendonly no \
  --loglevel warning \
  --maxmemory "${REDIS_MAXMEMORY:-256mb}" \
  --maxmemory-policy allkeys-lru &
redis_pid="$!"

log "starting Chroma server"
chroma run --path "$CHROMA_DIR" --host 127.0.0.1 --port "$CHROMA_PORT" &
chroma_pid="$!"

log "waiting for Chroma"
chroma_ready=false
for ((attempt = 1; attempt <= 90; attempt++)); do
  if python - <<'PY'
import os
import chromadb

client = chromadb.HttpClient(
    host=os.environ.get("CHROMA_HOST", "127.0.0.1"),
    port=int(os.environ.get("CHROMA_PORT", "8001")),
)
client.heartbeat()
PY
  then
    chroma_ready=true
    break
  fi
  sleep 1
done

if [ "$chroma_ready" != "true" ]; then
  log "Chroma did not answer before timeout"
  exit 1
fi

if ! kill -0 "$chroma_pid" 2>/dev/null; then
  log "Chroma exited during startup"
  exit 1
fi

log "starting periodic Chroma backup"
(
  while true; do
    sleep "$BACKUP_INTERVAL_SECONDS"
    python -m backend.core.chroma_backup backup --path "$CHROMA_DIR" || true
  done
) &
backup_pid="$!"

log "starting RQ worker"
rq worker ingestion ingestion_bulk --with-scheduler &
worker_pid="$!"

log "starting FastAPI on :7860"
uvicorn backend.main:app --host 0.0.0.0 --port 7860 --workers 1 &
api_pid="$!"

if ! wait -n "$redis_pid" "$chroma_pid" "$worker_pid" "$api_pid"; then
  log "a critical process exited with failure"
  exit 1
fi

log "a critical process exited"
exit 1

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

# Chroma readiness/liveness is probed over HTTP, not by PID: `chroma run`
# launches the server and its launcher process exits, so $chroma_pid is not a
# reliable handle on the running server.
chroma_up() {
  python - <<'PY' >/dev/null 2>&1
import os
import chromadb

chromadb.HttpClient(
    host=os.environ.get("CHROMA_HOST", "127.0.0.1"),
    port=int(os.environ.get("CHROMA_PORT", "8001")),
).heartbeat()
PY
}

log "waiting for Chroma"
chroma_ready=false
for ((attempt = 1; attempt <= 90; attempt++)); do
  if chroma_up; then
    chroma_ready=true
    break
  fi
  sleep 1
done

if [ "$chroma_ready" != "true" ]; then
  log "Chroma did not answer before timeout"
  exit 1
fi
log "Chroma is ready"

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

# Supervisor loop. The RQ worker and uvicorn are direct children, so a PID
# check is reliable; Chroma is probed over HTTP. If any critical process dies,
# exit non-zero so the trap tears the rest down and Hugging Face restarts.
while true; do
  sleep 15
  if ! kill -0 "$api_pid" 2>/dev/null; then
    log "FastAPI exited"
    exit 1
  fi
  if ! kill -0 "$worker_pid" 2>/dev/null; then
    log "RQ worker exited"
    exit 1
  fi
  if [ -n "$redis_pid" ] && ! kill -0 "$redis_pid" 2>/dev/null; then
    log "Redis exited"
    exit 1
  fi
  if ! chroma_up; then
    log "Chroma became unreachable"
    exit 1
  fi
done

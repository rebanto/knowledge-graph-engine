#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE=(docker compose -f docker-compose.prod.yml)

die() {
  echo "ERROR: $*" >&2
  exit 1
}

get_env() {
  local key="$1"
  awk -F= -v key="$key" '
    $1 == key {
      sub(/^[^=]*=/, "")
      sub(/\r$/, "")
      print
      exit
    }
  ' .env | sed -e 's/[[:space:]]#.*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

require_env() {
  local key="$1"
  local value
  value="$(get_env "$key")"
  if [ -z "$value" ] || [[ "$value" == *"<"* ]] || [[ "$value" == *"change-me"* ]] || [[ "$value" == *"CHANGE_ME"* ]]; then
    die "$key must be set in .env and must not be a placeholder"
  fi
}

wait_for_health() {
  local svc="$1"
  local expected="${2:-healthy}"
  local cid status

  echo "Waiting for ${svc} to become ${expected}..."
  for _ in $(seq 1 120); do
    cid="$("${COMPOSE[@]}" ps -q "$svc" 2>/dev/null | tail -n 1)"
    if [ -n "$cid" ]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      if [ "$status" = "$expected" ]; then
        return 0
      fi
    fi
    sleep 3
  done

  "${COMPOSE[@]}" logs --tail=120 "$svc" || true
  die "${svc} did not become ${expected}"
}

wait_for_url() {
  local url="$1"
  echo "Waiting for API readiness through Caddy: ${url}"
  for _ in $(seq 1 90); do
    if curl -fsS --max-time 5 "$url" >/dev/null; then
      return 0
    fi
    sleep 5
  done
  die "API readiness check failed at ${url}"
}

[ -f .env ] || die "Missing .env. Copy .env.prod.example to .env and fill it in first."

for key in GEMINI_API_KEY AUTH_SECRET_KEY NEO4J_PASSWORD POSTGRES_PASSWORD FRONTEND_ORIGIN COOKIE_SECURE USE_RERANKER USE_SHARDING ALLOW_PRIVATE_SOURCE_URLS RATE_LIMIT_ENABLED; do
  require_env "$key"
done

DOMAIN="$(get_env DOMAIN)"
COOKIE_SECURE="$(get_env COOKIE_SECURE)"
FRONTEND_ORIGIN="$(get_env FRONTEND_ORIGIN)"

if [ -n "$DOMAIN" ]; then
  [[ "$DOMAIN" != http://* && "$DOMAIN" != https://* ]] || die "DOMAIN should be a bare host name, not a URL"
  [ "$FRONTEND_ORIGIN" = "https://${DOMAIN}" ] || die "FRONTEND_ORIGIN must be https://${DOMAIN} when DOMAIN is set"
  [ "$COOKIE_SECURE" = "true" ] || die "COOKIE_SECURE must be true when DOMAIN is set"
  APP_URL="https://${DOMAIN}"
  HEALTH_URL="${APP_URL}/health/ready"
else
  [[ "$FRONTEND_ORIGIN" == http://* ]] || die "HTTP mode needs FRONTEND_ORIGIN=http://<server-ip-or-host>"
  [ "$COOKIE_SECURE" = "false" ] || die "HTTP mode needs COOKIE_SECURE=false"
  APP_URL="$FRONTEND_ORIGIN"
  HEALTH_URL="http://127.0.0.1/health/ready"
fi

AUTH_SECRET_KEY="$(get_env AUTH_SECRET_KEY)"
[ "${#AUTH_SECRET_KEY}" -ge 32 ] || die "AUTH_SECRET_KEY should be at least 32 characters"
[ "$(get_env USE_SHARDING)" = "false" ] || die "Production compose is single-node; set USE_SHARDING=false"

git pull --ff-only

"${COMPOSE[@]}" config >/dev/null
"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d

for svc in postgres redis neo4j chroma api worker caddy; do
  wait_for_health "$svc"
done

wait_for_url "$HEALTH_URL"

cat <<EOF

Knowledge Graph Research Engine is deployed.

URL: ${APP_URL}
Health: ${HEALTH_URL}

Service status:
EOF
"${COMPOSE[@]}" ps

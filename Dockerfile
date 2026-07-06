FROM node:20-alpine AS frontend

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
# Leave VITE_API_URL unset so the built app uses same-origin /api paths.
RUN npm run build


FROM caddy:2-alpine AS caddy

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /app/frontend/dist /srv


FROM python:3.11-slim AS api

WORKDIR /app

ARG TARGETARCH

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    SENTENCE_TRANSFORMERS_HOME=/opt/hf/sentence-transformers \
    TRANSFORMERS_CACHE=/opt/hf/transformers \
    HF_HUB_DISABLE_TELEMETRY=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.7.1+cpu"; \
    fi
RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" \
    && chmod -R a+rX /opt/hf

ENV HF_HUB_OFFLINE=1

COPY backend/ ./backend/
COPY proto/ ./proto/
COPY scripts/ ./scripts/
COPY --from=frontend /app/frontend/dist ./frontend_dist/

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]


FROM api AS space

USER root

ENV HF_HUB_OFFLINE=0 \
    STATIC_DIR=/app/frontend_dist \
    CHROMA_PERSIST_DIR=/data/chroma \
    CHROMA_HOST=127.0.0.1 \
    CHROMA_PORT=8001 \
    REDIS_URL=redis://127.0.0.1:6379 \
    USE_SHARDING=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('all-MiniLM-L6-v2'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')" \
    && chmod -R a+rX /opt/hf

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app \
    && mkdir -p /data/chroma \
    && chown -R app:app /app /data /opt/hf

RUN chmod +x /app/scripts/space_entrypoint.sh

USER app

EXPOSE 7860

ENTRYPOINT ["/app/scripts/space_entrypoint.sh"]

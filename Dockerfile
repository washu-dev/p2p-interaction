# ---- Stage 1: build the React app (the single UI) ----
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# No VITE_API_BASE_URL here: the container serves this build at its own origin,
# so relative /api calls are same-origin. (CloudFront builds its own copy.)
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.11-slim AS base

# Surfaced via /api/health so a deployed task reports what's actually running.
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV GIT_SHA=${GIT_SHA}
ENV BUILD_TIME=${BUILD_TIME}

# Security: run as non-root
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Patch OS packages before installing app deps
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Install app deps, then force-upgrade toolchain packages that carry known CVEs
# in the base image (wheel, jaraco.context). Done after requirements so nothing
# can downgrade them.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && \
    pip install --no-cache-dir "wheel>=0.46.2" "jaraco.context>=6.1.0"

# Copy application code preserving the directory layout config.py expects:
#   BASE_DIR     = /app/backend
#   GUI_DIR      = /app
#   FRONTEND_DIR = /app/web/dist   (the built React app, served by FastAPI)
#   DATA_DIR     = /app/data       (overridable via BINDGUI_DATA_DIR)
COPY backend/ backend/
COPY --from=web /web/dist web/dist

RUN mkdir -p data/jobs && chmod +x backend/entrypoint.sh && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# entrypoint.sh fetches DB_PASSWORD from AWS Secrets Manager into backend/config.json
# (skipped for BINDGUI_BACKEND=mock) then execs uvicorn, launched from project root
# so --app-dir backend keeps relative paths intact.
ENTRYPOINT ["backend/entrypoint.sh"]

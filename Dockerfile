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

RUN mkdir -p data/jobs && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Launched from project root so --app-dir backend keeps relative paths intact
CMD ["uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]

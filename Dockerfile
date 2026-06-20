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
#   BASE_DIR = /app/backend
#   GUI_DIR  = /app
#   DATA_DIR = /app/data  (overridable via BINDGUI_DATA_DIR)
COPY backend/ backend/
COPY frontend/ frontend/

RUN mkdir -p data/jobs && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Launched from project root so --app-dir backend keeps relative paths intact
CMD ["uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]

#!/bin/sh
set -e

python backend/fetch_secrets.py

exec uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000

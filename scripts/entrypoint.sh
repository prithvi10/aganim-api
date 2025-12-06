#!/bin/bash
set -e

# 1. Run Database Seeding (Idempotent)
# This ensures plans and initial data exist before the app takes traffic
echo "🌱 Seeding database..."
python -m scripts.seed_db

# 2. Start the Application
# Render sets the PORT environment variable. We default to 8000 if not set.
PORT=${PORT:-8000}
echo "🚀 Starting server on port $PORT..."

# Use exec to replace the shell process with uvicorn (better signal handling)
exec uvicorn src.main.api.main:app --host 0.0.0.0 --port $PORT


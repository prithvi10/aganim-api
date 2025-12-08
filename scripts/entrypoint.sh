#!/bin/bash
set -e

# 1. Wait for Database to be Ready
# This prevents the app from crashing if the DB isn't up yet (common in Docker Compose)
echo "⏳ Checking database connection..."
python -m scripts.wait_for_db

# 2. Run Database Seeding (Idempotent)
# This creates tables (if missing) and ensures plans/initial data exist
echo "🌱 Seeding database..."
python -m scripts.seed_db

# 2. Start the Application
# Render sets the PORT environment variable. We default to 8000 if not set.
PORT=${PORT:-8000}
echo "🚀 Starting server on port $PORT..."

# Use exec to replace the shell process with uvicorn (better signal handling)
exec uvicorn src.main.api.main:app --host 0.0.0.0 --port $PORT


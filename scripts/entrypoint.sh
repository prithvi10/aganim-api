#!/bin/bash
set -e

# 1. Wait for Database to be Ready
echo "Checking database connection..."
python -m scripts.wait_for_db

# 2. Run Alembic Migrations (idempotent — safe to re-run)
echo "Running database migrations..."
alembic upgrade head

# 3. Run Database Seeding (Idempotent)
echo "Seeding database..."
python -m scripts.seed_db

# 4. Start the Application
# Render sets the PORT environment variable. We default to 8000 if not set.
PORT=${PORT:-8000}
echo "Starting server on port $PORT..."

exec uvicorn src.ecommerce.api.main:app --host 0.0.0.0 --port $PORT


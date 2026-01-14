from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
import uvicorn
import os
from contextlib import asynccontextmanager

from src.main.config.configs import DATABASE_URL, ALLOWED_ORIGINS
from src.main.db.database import engine, Base, get_db
from src.main.api.controller import router as api_router


def _ensure_shop_columns_exist():
    """Best-effort schema evolution for shops table (no migrations in this repo).

    SQLite: check PRAGMA table_info then ALTER TABLE ADD COLUMN
    Postgres: ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    """
    dialect = engine.dialect.name
    if dialect == "sqlite":
        with engine.connect() as conn:
            cols = conn.execute(text("PRAGMA table_info(shops)")).fetchall()
            existing = {c[1] for c in cols}

            def add(col_sql: str, col_name: str):
                if col_name in existing:
                    return
                conn.execute(text(f"ALTER TABLE shops ADD COLUMN {col_sql}"))

            add("monthly_rewrites_used INTEGER DEFAULT 0", "monthly_rewrites_used")
            add("reset_anchor_date TEXT", "reset_anchor_date")
            add("next_reset_date TEXT", "next_reset_date")
            add("fair_use_last_notified_at TEXT", "fair_use_last_notified_at")
            add("monthly_cost_accumulated REAL DEFAULT 0", "monthly_cost_accumulated")
            conn.commit()
        return

    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS monthly_rewrites_used INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS reset_anchor_date TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS next_reset_date TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS fair_use_last_notified_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS monthly_cost_accumulated NUMERIC(12,2) DEFAULT 0"))
        conn.commit()


def _ensure_plan_columns_exist():
    """Best-effort schema evolution for plans table (no migrations in this repo)."""
    dialect = engine.dialect.name
    if dialect == "sqlite":
        with engine.connect() as conn:
            cols = conn.execute(text("PRAGMA table_info(plans)")).fetchall()
            existing = {c[1] for c in cols}

            def add(col_sql: str, col_name: str):
                if col_name in existing:
                    return
                conn.execute(text(f"ALTER TABLE plans ADD COLUMN {col_sql}"))

            add("product_limit INTEGER", "product_limit")
            add("max_locales INTEGER", "max_locales")
            add("features_json TEXT", "features_json")
            conn.commit()
        return

    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS product_limit INTEGER"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_locales INTEGER"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS features_json TEXT"))
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables
    Base.metadata.create_all(bind=engine)
    _ensure_plan_columns_exist()
    _ensure_shop_columns_exist()
    yield
    # Shutdown: (Cleanup if needed)

app = FastAPI(lifespan=lifespan)

# ------------------------------------------------------------------
# CORS Configuration
# ------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Regex to allow any Shopify store domain (e.g., https://my-store.myshopify.com)
    allow_origin_regex=r"https://.*\.myshopify\.com|https://admin\.shopify\.com|https://extensions\.shopifycdn\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the API router
app.include_router(api_router)

# Health Check Endpoint
@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for cloud providers.
    Checks:
    1. App is running (returns 200)
    2. Database connection is active
    """
    try:
        # Simple query to verify DB connection
        db.execute(text("SELECT 1"))
        return JSONResponse(status_code=200, content={"status": "healthy", "database": "connected"})
    except Exception as e:
        return JSONResponse(
            status_code=503, 
            content={"status": "unhealthy", "database": "disconnected", "error": str(e)}
        )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

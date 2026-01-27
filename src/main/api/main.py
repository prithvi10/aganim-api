from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
import uvicorn
import os
from contextlib import asynccontextmanager
from time import perf_counter
import uuid

from src.main.config.configs import DATABASE_URL, ALLOWED_ORIGINS
from src.main.db.database import engine, Base, get_db
from src.main.api.controller import router as api_router
from src.main.logging.logger import get_logger

request_logger = get_logger("api.request")


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
            add("lifetime_rewrites_remaining INTEGER DEFAULT 10", "lifetime_rewrites_remaining")
            add("is_active INTEGER DEFAULT 1", "is_active")
            add("welcome_back_pending INTEGER DEFAULT 0", "welcome_back_pending")
            add("access_expires_at TEXT", "access_expires_at")
            add("current_plan_name TEXT", "current_plan_name")
            add("last_plan_name TEXT", "last_plan_name")
            add("last_uninstalled_at TEXT", "last_uninstalled_at")
            add("reset_anchor_date TEXT", "reset_anchor_date")
            add("next_reset_date TEXT", "next_reset_date")
            add("fair_use_last_notified_at TEXT", "fair_use_last_notified_at")
            add("monthly_cost_accumulated REAL DEFAULT 0", "monthly_cost_accumulated")
            add("onboarding_step INTEGER DEFAULT 0", "onboarding_step")
            add("is_onboarding_finished INTEGER DEFAULT 0", "is_onboarding_finished")
            add("pending_plan_name TEXT", "pending_plan_name")
            add("pending_plan_effective_at TEXT", "pending_plan_effective_at")
            add("last_plan_change_type TEXT", "last_plan_change_type")
            add("last_plan_change_at TEXT", "last_plan_change_at")
            add("last_shopify_subscription_status TEXT", "last_shopify_subscription_status")
            add("brand_context_summary TEXT", "brand_context_summary")
            add("brand_context_summary_en TEXT", "brand_context_summary_en")
            add("brand_context_summary_ja TEXT", "brand_context_summary_ja")
            add("brand_context_updated_at TEXT", "brand_context_updated_at")
            add("brand_context_status TEXT", "brand_context_status")
            add("brand_context_last_error TEXT", "brand_context_last_error")
            add("brand_context_job_id TEXT", "brand_context_job_id")
            conn.commit()
        return

    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS monthly_rewrites_used INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS lifetime_rewrites_remaining INTEGER DEFAULT 10"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS welcome_back_pending BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS access_expires_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS current_plan_name VARCHAR"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS last_plan_name VARCHAR"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS last_uninstalled_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS reset_anchor_date TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS next_reset_date TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS fair_use_last_notified_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS monthly_cost_accumulated NUMERIC(12,2) DEFAULT 0"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS onboarding_step INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS is_onboarding_finished BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS pending_plan_name VARCHAR"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS pending_plan_effective_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS last_plan_change_type VARCHAR"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS last_plan_change_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS last_shopify_subscription_status VARCHAR"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS brand_context_summary TEXT"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS brand_context_summary_en TEXT"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS brand_context_summary_ja TEXT"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS brand_context_updated_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS brand_context_status VARCHAR"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS brand_context_last_error TEXT"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS brand_context_job_id VARCHAR"))
        conn.commit()


def _ensure_pgvector_extension_and_indexes():
    """Best-effort pgvector extension + indexes for store_context (Postgres only)."""
    if engine.dialect.name != "postgresql":
        return
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS store_context_shop_id_idx ON store_context (shop_id)"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS store_context_embedding_idx "
                "ON store_context USING ivfflat (embedding vector_cosine_ops)"
            )
        )
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
            add("billing_cycle_type TEXT", "billing_cycle_type")
            conn.commit()
        return

    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS product_limit INTEGER"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_locales INTEGER"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS features_json TEXT"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS billing_cycle_type TEXT"))
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables
    Base.metadata.create_all(bind=engine)
    _ensure_plan_columns_exist()
    _ensure_shop_columns_exist()
    _ensure_pgvector_extension_and_indexes()
    yield
    # Shutdown: (Cleanup if needed)

app = FastAPI(lifespan=lifespan)

# ------------------------------------------------------------------
# Request/Response Logging (production-grade, minimal)
# - Adds/propagates X-Request-Id
# - Logs method/path/status/latency and safe shop context
# ------------------------------------------------------------------
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = (request.headers.get("X-Request-Id") or "").strip() or uuid.uuid4().hex[:12]
    request.state.request_id = request_id

    method = request.method
    path = request.url.path
    skip_logging = path == "/health"

    # Safe context only (never log tokens/signatures/bodies)
    shop = (
        (request.headers.get("X-Shopify-Shop-Domain") or "").strip()
        or (request.query_params.get("shop") or "").strip()
        or "-"
    )

    start = perf_counter()
    try:
        if not skip_logging:
            request_logger.info("[REQ] rid=%s %s %s shop=%s", request_id, method, path, shop)
        response = await call_next(request)
    except Exception:
        dur_ms = (perf_counter() - start) * 1000.0
        if not skip_logging:
            request_logger.exception(
                "[ERR] rid=%s %s %s shop=%s dur_ms=%.1f", request_id, method, path, shop, dur_ms
            )
        raise

    dur_ms = (perf_counter() - start) * 1000.0
    response.headers["X-Request-Id"] = request_id
    if not skip_logging:
        request_logger.info(
            "[RES] rid=%s %s %s status=%s dur_ms=%.1f",
            request_id,
            method,
            path,
            getattr(response, "status_code", None),
            dur_ms,
        )
    return response

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

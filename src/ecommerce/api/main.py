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
from src.ecommerce.config.configs import DATABASE_URL, ALLOWED_ORIGINS
from src.shared.db.database import engine, Base, get_db
from src.ecommerce.api.controller import router as api_router
from src.shared.logging.logger import get_logger

_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_sentry_dsn,
            traces_sample_rate=0.1,
            environment=os.getenv("ENVIRONMENT", "development"),
        )
    except ImportError:
        pass

request_logger = get_logger("api.request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # In test / local-dev mode (SQLite) create tables from model metadata.
    # Production schema is managed exclusively by Alembic migrations.
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine)
    yield

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
    allow_origin_regex=r"https://.*\.myshopify\.com|https://admin\.shopify\.com|https://extensions\.shopifycdn\.com|https://.*\.ngrok\.app|https://.*\.trycloudflare\.com",
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

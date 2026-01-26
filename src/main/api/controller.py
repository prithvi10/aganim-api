from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query, Header, BackgroundTasks
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import secrets
import os
import jwt
from pydantic import ValidationError

from .models import (
    RewriteRequest,
    OnboardingRequest,
    BulkRewriteRequest,
    AgentRequest,
    BrandContextIngestRequest,
    BrandContextFileExtractRequest,
)
from src.main.db.db_models import User
from src.main.db.database import get_db, SessionLocal
from src.main.db.db_transactions import (
    get_plan_by_name,
    get_shop_quota_context,
    store_shop_access_token,
    record_successful_rewrite,
)
from src.main.db.db_transactions import get_user_by_username
from src.main.db.db_models import Shop, User, Plan, StoreContext
from src.main.security.security import (
    verify_shopify_session, 
    verify_webhook_signature, 
    verify_shopify_redirect,
    verify_shopify_proxy_request,
    SHOPIFY_API_KEY,
    SHOPIFY_API_SECRET
)
from src.main.api.validation import validate_rewrite_request, validate_shop_and_quota 
from src.main.service.onboarding import onboard_user
from src.main.service.brand_context_ingest import ingest_brand_context, scrape_urls, extract_file_text
from src.main.config.configs import SHOPIFY_UI_URL, PROMO_PRICING_ENABLED
from src.main.logging.logger import get_logger, get_security_logger
from typing import Optional

# Import core business logic
from src.main.core.generation import process_generation_request, process_bulk_generation_request
from src.main.core.shop import fetch_shop_locales
from src.main.core.agent_actions import run_agent_action

logger = get_logger(__name__)
security_logger = get_security_logger("security.webhooks")

router = APIRouter()

# Backwards-compat for older tests/patches that expect this symbol on the controller module.
increment_monthly_rewrites_used = record_successful_rewrite

SCOPES = "read_products,write_products,read_locales,read_translations,write_translations,read_files"
SHOPIFY_REDIRECT_URI = "https://shopify-translator-api.onrender.com/api/auth/callback"
TOKEN_SYNC_SECRET = os.getenv("TOKEN_SYNC_SECRET")


# ==============================================================================
#  Shared dependency: determine the shop for both Theme App Proxy and Admin UI Extensions
#  - Theme App Proxy: verify Shopify proxy signature (HMAC) on the full Request
#  - Admin UI Extensions: verify Shopify session token (JWT) from Authorization header
#
#  IMPORTANT:
#  - `verify_shopify_session()` already returns a shop domain string (not a payload dict)
#  - `verify_shopify_proxy_request()` expects the full FastAPI Request
# ==============================================================================
async def resolve_shop_domain(request: Request) -> str:
    auth_header = request.headers.get("Authorization") or ""

    # Path A: Admin Action / embedded app call (JWT)
    if auth_header.startswith("Bearer "):
        try:
            return verify_shopify_session(auth_header)
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid Admin Token")

    # Path B: Theme App Proxy (HMAC)
    try:
        return await verify_shopify_proxy_request(request)
    except HTTPException:
        raise


def _rid(request: Optional[Request]) -> str:
    try:
        return str(getattr(getattr(request, "state", None), "request_id", "") or "-")
    except Exception:
        return "-"

# ==============================================================================
#  0. OAUTH ENTRY POINT (Install App)
# ==============================================================================
@router.get("/")
async def install_app(request: Request, shop: str = Query(..., description="Shopify Shop Domain")):
    """
    Redirects the user to Shopify's OAuth authorization page.
    """
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")
    
    logger.info("[Install] start rid=%s shop=%s", _rid(request), shop)

    state = secrets.token_hex(16)
    
    authorization_url = (
        f"https://{shop}/admin/oauth/authorize?"
        f"client_id={SHOPIFY_API_KEY}&"
        f"scope={SCOPES}&"
        f"redirect_uri={SHOPIFY_REDIRECT_URI}&"
        f"state={state}"
    )
    
    return RedirectResponse(url=authorization_url, status_code=307)


# ==============================================================================
#  1. APP PROXY ENDPOINT (Securely used by Shopify Theme Frontend)
# ==============================================================================
@router.post("/api/proxy/generate-copy")
async def proxy_generate_copy(
    request: Request,
    db: Session = Depends(get_db)
):
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        logger.info("[Copy] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    try:
        rewrite_request = RewriteRequest(**body)
    except ValidationError as e:
        logger.info("[Copy] invalid_payload rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())

    validate_rewrite_request(rewrite_request.model_dump())

    shop_domain = request.query_params.get("shop")
    if not shop_domain:
         logger.info("[Copy] missing_shop rid=%s", rid)
         raise HTTPException(status_code=400, detail="Missing shop parameter")

    logger.info(
        "[Copy] start rid=%s shop=%s target=%s has_product_id=%s desc_len=%s name_len=%s",
        rid,
        shop_domain,
        getattr(rewrite_request, "target_locale", None),
        bool(getattr(rewrite_request, "product_id", None)),
        len(getattr(rewrite_request, "japanese_description", "") or ""),
        len(getattr(rewrite_request, "product_name", "") or ""),
    )

    auth_context = validate_shop_and_quota(db, shop_domain, enforce_limit=True)
    try:
        logger.info(
            "[Copy] auth_ok rid=%s shop=%s plan=%s",
            rid,
            shop_domain,
            getattr(auth_context.get("plan"), "name", None),
        )
    except Exception:
        pass
    
    # Delegate business logic to Core layer
    resp = await process_generation_request(
        db=db,
        request=rewrite_request,
        user=auth_context["user"],
        plan=auth_context["plan"],
    )
    # Increment rewrite usage after successful generation
    if isinstance(resp, dict) and resp.get("status") == "success":
        try:
            record_successful_rewrite(db, shop_domain, amount=1)
        except Exception as e:
            logger.warning(f"Rewrite increment skipped for shop={shop_domain}: {e}")
    try:
        logger.info(
            "[Copy] done rid=%s shop=%s status=%s",
            rid,
            shop_domain,
            resp.get("status") if isinstance(resp, dict) else type(resp).__name__,
        )
    except Exception:
        pass
    return resp


@router.post("/api/proxy/generate-bulk")
async def proxy_generate_bulk(
    request: Request,
    db: Session = Depends(get_db),
    shop_domain: str = Depends(resolve_shop_domain),
):
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        logger.info("[Bulk] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    try:
        bulk_request = BulkRewriteRequest(**body)
    except ValidationError as e:
        logger.info("[Bulk] invalid_payload rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())

    # DEBUG: safe request summary (never log tokens or full text)
    try:
        logger.debug(
            "[Bulk] incoming shop=%s product_id=%s target_locales=%s desc_len=%s name_len=%s category=%s",
            shop_domain,
            getattr(bulk_request, "product_id", None),
            getattr(bulk_request, "target_locales", None),
            len(getattr(bulk_request, "japanese_description", "") or ""),
            len(getattr(bulk_request, "product_name", "") or ""),
            getattr(bulk_request, "category", None),
        )
    except Exception:
        pass

    auth_context = validate_shop_and_quota(db, shop_domain, enforce_limit=True)
    try:
        plan = auth_context.get("plan")
        shop_obj = auth_context.get("shop")
        logger.debug(
            "[Bulk] auth ok shop=%s plan=%s rewrites_used=%s rewrite_limit=%s next_reset=%s max_locales=%s",
            shop_domain,
            getattr(plan, "name", None),
            auth_context.get("rewrites_used"),
            auth_context.get("rewrite_limit"),
            getattr(shop_obj, "next_reset_date", None),
            getattr(plan, "max_locales", None),
        )
    except Exception:
        pass
    
    try:
        resp = await process_bulk_generation_request(
        db=db,
        request=bulk_request,
        user=auth_context["user"],
        plan=auth_context["plan"],
        )
    except HTTPException:
        logger.exception("[Bulk] http_error rid=%s shop=%s", rid, shop_domain)
        raise
    except Exception:
        logger.exception("[Bulk] unhandled_error rid=%s shop=%s", rid, shop_domain)
        raise

    try:
        logger.debug(
            "[Bulk] result shop=%s status=%s processed=%s failed=%s has_results=%s",
            shop_domain,
            resp.get("status") if isinstance(resp, dict) else type(resp).__name__,
            len(resp.get("processed", [])) if isinstance(resp, dict) else None,
            len(resp.get("failed", [])) if isinstance(resp, dict) else None,
            bool(resp.get("results")) if isinstance(resp, dict) else None,
        )
    except Exception:
        pass

    if isinstance(resp, dict) and resp.get("status") == "success":
        try:
            record_successful_rewrite(db, shop_domain, amount=1)
        except Exception as e:
            logger.warning(f"Rewrite increment skipped for shop={shop_domain}: {e}")
    return resp


# ==============================================================================
#  1B. ADMIN EXTENSION ENDPOINT (Used by Shopify Admin UI Extensions)
#      NOTE: Admin extensions are hosted on https://extensions.shopifycdn.com
#      and will send Authorization: Bearer <Shopify session token>.
# ==============================================================================
@router.options("/apps/cross-border/generate-bulk")
async def admin_ext_generate_bulk_preflight():
    # CORSMiddleware will generally handle this, but we provide an explicit
    # handler to avoid surprises in some deployment/proxy setups.
    return Response(status_code=204)


@router.post("/apps/cross-border/generate-bulk")
async def admin_ext_generate_bulk(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Bulk generation endpoint for Shopify Admin Action extensions.
    Authenticated using a Shopify Session Token (JWT) sent via Authorization header.
    """
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        logger.info("[AdminBulk] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    try:
        bulk_request = BulkRewriteRequest(**body)
    except ValidationError as e:
        logger.info("[AdminBulk] invalid_payload rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())

    logger.info(
        "[AdminBulk] start rid=%s shop=%s product_id=%s target_locales=%s",
        rid,
        shop,
        getattr(bulk_request, "product_id", None),
        getattr(bulk_request, "target_locales", None),
    )
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=True)

    resp = await process_bulk_generation_request(
        db=db,
        request=bulk_request,
        user=auth_context["user"],
        plan=auth_context["plan"],
    )
    if isinstance(resp, dict) and resp.get("status") == "success":
        try:
            record_successful_rewrite(db, shop, amount=1)
        except Exception as e:
            logger.warning(f"Rewrite increment skipped for shop={shop}: {e}")
    try:
        logger.info(
            "[AdminBulk] done rid=%s shop=%s status=%s processed=%s failed=%s",
            rid,
            shop,
            resp.get("status") if isinstance(resp, dict) else type(resp).__name__,
            len(resp.get("processed", [])) if isinstance(resp, dict) else None,
            len(resp.get("failed", [])) if isinstance(resp, dict) else None,
    )
    except Exception:
        pass
    return resp


# ==============================================================================
#  1C. ADMIN EXTENSION AGENT ENDPOINT (Action-based, backend-agnostic)
#      Standardized payload:
#        { "action": string, "context": object, "product_data": object }
#      Standardized response:
#        { "status": "success", "data": { "text": string, "metadata": object } }
# ==============================================================================
@router.options("/apps/cross-border/agent")
async def admin_ext_agent_preflight():
    return Response(status_code=204)


@router.post("/apps/cross-border/agent")
async def admin_ext_agent(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Action-based endpoint for Shopify Admin UI extensions.
    Authenticated using a Shopify OpenID Connect ID token / session token (JWT) via Authorization header.
    """
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        logger.info("[Agent] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    try:
        agent_req = AgentRequest(**body)
    except ValidationError as e:
        logger.info("[Agent] invalid_payload rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())

    # Agents are also gated by monthly rewrite limits.
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=True)

    logger.info("[Agent] start rid=%s shop=%s action=%s", rid, shop, agent_req.action)

    # Propagate request id into action context for end-to-end traceability.
    try:
        if agent_req.context is None:
            agent_req.context = {}
        if isinstance(agent_req.context, dict) and "request_id" not in agent_req.context:
            agent_req.context["request_id"] = rid
    except Exception:
        pass

    result = run_agent_action(
        action=agent_req.action,
        context=agent_req.context or {},
        product_data=agent_req.product_data or {},
    )

    logger.info("[Agent] done rid=%s shop=%s action=%s", rid, shop, agent_req.action)
    return {"status": "success", "data": {"text": result.get("text", ""), "metadata": result.get("metadata", {})}}


# ==============================================================================
#  2. DIRECT API ENDPOINT (DEPRECATED/REMOVED)
# ==============================================================================
@router.post("/api/generate-copy")
async def generate_copy(
    request: RewriteRequest,
    db: Session = Depends(get_db)
):
    raise HTTPException(status_code=410, detail="This endpoint is deprecated. Please use the Shopify App Proxy.")


# ==============================================================================
#  3. WEBHOOKS & AUTH (Shopify Admin)
# ==============================================================================
@router.get("/api/admin/me")
async def get_admin_info(
    request: Request,
    shop: str = Depends(verify_shopify_session)
):
    logger.info("[AdminMe] rid=%s shop=%s", _rid(request), shop)
    return {"status": "authenticated", "shop": shop, "message": "Welcome to the Admin API"}


@router.get("/api/admin/usage")
async def get_usage(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Returns current usage and plan info for the shop.
    Authenticated via shop query param (internal/proxy usage).
    """
    shop_domain = request.query_params.get("shop")
    if not shop_domain:
        # Try finding it in headers if passed by proxy or middleware
        shop_domain = request.headers.get("X-Shopify-Shop-Domain")
        
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    logger.info("[Usage] start rid=%s shop=%s", _rid(request), shop_domain)
    # Dashboard/status should never hard-fail on quota; it should show the current usage + reset date.
    auth_context = validate_shop_and_quota(db, shop_domain, enforce_limit=False)
    
    user = auth_context["user"]
    plan = auth_context["plan"]
    shop = auth_context["shop"]
    rewrites_used = auth_context["rewrites_used"]
    rewrite_limit = auth_context["rewrite_limit"]
    billing_cycle_type = str(auth_context.get("billing_cycle_type") or getattr(plan, "billing_cycle_type", "") or "").strip().lower()
    if not billing_cycle_type:
        billing_cycle_type = "lifetime" if str(getattr(plan, "name", "") or "") == "Free" else "recurring"
    lifetime_remaining = int(auth_context.get("lifetime_rewrites_remaining") or 0)
    next_reset = auth_context.get("next_reset_date")
    
    welcome_back = False
    try:
        welcome_back = bool(getattr(shop, "welcome_back_pending", False))
        if welcome_back:
            shop.welcome_back_pending = False
            db.add(shop)
            db.commit()
            db.refresh(shop)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    
    return {
        # DB is source-of-truth: use effective_plan_name for UI display/gating.
        "plan_name": (auth_context.get("effective_plan_name") or plan.name),
        # Product rewrite usage (new system)
        "monthly_rewrites_used": rewrites_used,
        "rewrite_limit": rewrite_limit,
        "next_reset_date": next_reset.isoformat() if next_reset else None,
        # Lifetime plan fields (Free)
        "billing_cycle_type": billing_cycle_type,
        "lifetime_rewrites_remaining": lifetime_remaining if billing_cycle_type == "lifetime" else None,
        # Backward compatibility (old keys mapped to new system)
        "current_usage": rewrites_used,
        "monthly_token_quota": rewrite_limit,
        # Feature gating fields
        "product_limit": plan.product_limit,
        "max_locales": plan.max_locales,
        "features_json": plan.features_json,
        "is_pro": plan.name in ("Standard", "Pro"),
        "welcome_back": welcome_back,
        # Grace period / reinstall metadata
        "access_expires_at": (auth_context.get("access_expires_at").isoformat() if auth_context.get("access_expires_at") else None),
        "grace_active": bool(auth_context.get("grace_active")),
        "grace_mode": bool(auth_context.get("grace_mode")),
        "last_plan_name": auth_context.get("last_plan_name"),
        "last_uninstalled_at": (auth_context.get("last_uninstalled_at").isoformat() if auth_context.get("last_uninstalled_at") else None),
        # UI feature flags
        "promo_pricing_enabled": bool(PROMO_PRICING_ENABLED),
        # Onboarding wizard status
        "is_onboarding_finished": bool(getattr(shop, "is_onboarding_finished", False)),
        "onboarding_step": int(getattr(shop, "onboarding_step", 0) or 0),
        # DB plan source-of-truth + downgrade metadata
        "effective_plan_name": auth_context.get("effective_plan_name") or (getattr(shop, "current_plan_name", None) or plan.name),
        "current_plan_name": getattr(shop, "current_plan_name", None),
        "pending_plan_name": getattr(shop, "pending_plan_name", None),
        "pending_plan_effective_at": (getattr(shop, "pending_plan_effective_at", None).isoformat() if getattr(shop, "pending_plan_effective_at", None) else None),
        "last_plan_change_type": getattr(shop, "last_plan_change_type", None),
        "last_plan_change_at": (getattr(shop, "last_plan_change_at", None).isoformat() if getattr(shop, "last_plan_change_at", None) else None),
    }


@router.post("/api/onboarding/update_step")
async def onboarding_update_step(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Persist onboarding wizard progress so merchants can leave and come back.
    Auth: internal (shop param / header); do NOT expose any billing limits to merchants.
    """
    shop_domain = (request.query_params.get("shop") or "").strip() or (request.headers.get("X-Shopify-Shop-Domain") or "").strip()
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    step = int(payload.get("step") or 0)
    if step < 0:
        step = 0
    if step > 4:
        step = 4
    mark_finished = bool(payload.get("is_onboarding_finished") or payload.get("finished") or False) or step >= 4

    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    try:
        cur_step = int(getattr(shop, "onboarding_step", 0) or 0)
        shop.onboarding_step = max(cur_step, step)
        if mark_finished:
            shop.is_onboarding_finished = True
            shop.onboarding_step = 4
        db.add(shop)
        db.commit()
        db.refresh(shop)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to update onboarding progress")

    return {
        "ok": True,
        "shop": shop_domain,
        "onboarding_step": int(getattr(shop, "onboarding_step", 0) or 0),
        "is_onboarding_finished": bool(getattr(shop, "is_onboarding_finished", False)),
    }


@router.post("/api/admin/brand-context/ingest")
async def brand_context_ingest_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Ingest brand context from URLs and/or wizard text inputs.
    Authenticated via Shopify session token or proxy signature.
    """
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        payload = BrandContextIngestRequest(**body)
    except ValidationError as e:
        logger.info("[BrandIngest] invalid_payload rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())

    raw_texts: list[dict] = []
    if payload.urls:
        raw_texts.extend(scrape_urls(payload.urls))

    wizard_blocks = []
    if payload.brand_persona:
        wizard_blocks.append(f"Brand Persona: {payload.brand_persona}")
    if payload.core_pillars:
        pillars = [str(p).strip() for p in payload.core_pillars if str(p).strip()]
        if pillars:
            wizard_blocks.append("Core Pillars:\n" + "\n".join(f"- {p}" for p in pillars))
    if payload.raw_text:
        wizard_blocks.append(str(payload.raw_text))
    if payload.file_text:
        wizard_blocks.append(str(payload.file_text))
    if wizard_blocks:
        raw_texts.append(
            {
                "source_url": None,
                "source_type": "wizard",
                "text": "\n\n".join(wizard_blocks),
            }
        )

    if not raw_texts:
        raise HTTPException(status_code=400, detail="No brand context content provided")

    result = ingest_brand_context(db, shop_id=shop, raw_texts=raw_texts)
    logger.info(
        "[BrandIngest] done rid=%s shop=%s inserted=%s chunks=%s",
        rid,
        shop,
        result.get("inserted"),
        result.get("chunk_count"),
    )
    return {"status": "success", **result}


def _run_brand_context_ingest(
    *,
    shop_id: str,
    raw_texts: list[dict],
    job_id: str,
) -> None:
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(Shop.domain == shop_id).first()
        if shop:
            shop.brand_context_status = "running"
            shop.brand_context_last_error = None
            shop.brand_context_job_id = job_id
            db.add(shop)
            db.commit()

        ingest_brand_context(db, shop_id=shop_id, raw_texts=raw_texts)

        shop = db.query(Shop).filter(Shop.domain == shop_id).first()
        if shop:
            shop.brand_context_status = "ready"
            shop.brand_context_last_error = None
            shop.brand_context_job_id = job_id
            db.add(shop)
            db.commit()
    except Exception as e:
        try:
            shop = db.query(Shop).filter(Shop.domain == shop_id).first()
            if shop:
                shop.brand_context_status = "failed"
                shop.brand_context_last_error = str(e)
                shop.brand_context_job_id = job_id
                db.add(shop)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/api/admin/brand-context/ingest-async")
async def brand_context_ingest_async_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Async ingestion: returns immediately and processes in background.
    """
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        payload = BrandContextIngestRequest(**body)
    except ValidationError as e:
        logger.info("[BrandIngest] async_invalid rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())

    raw_texts: list[dict] = []
    if payload.urls:
        raw_texts.extend(scrape_urls(payload.urls))

    wizard_blocks = []
    if payload.brand_persona:
        wizard_blocks.append(f"Brand Persona: {payload.brand_persona}")
    if payload.core_pillars:
        pillars = [str(p).strip() for p in payload.core_pillars if str(p).strip()]
        if pillars:
            wizard_blocks.append("Core Pillars:\n" + "\n".join(f"- {p}" for p in pillars))
    if payload.raw_text:
        wizard_blocks.append(str(payload.raw_text))
    if payload.file_text:
        wizard_blocks.append(str(payload.file_text))
    if wizard_blocks:
        raw_texts.append(
            {
                "source_url": None,
                "source_type": "wizard",
                "text": "\n\n".join(wizard_blocks),
            }
        )

    if not raw_texts:
        raise HTTPException(status_code=400, detail="No brand context content provided")

    import uuid

    job_id = uuid.uuid4().hex[:12]
    background_tasks.add_task(_run_brand_context_ingest, shop_id=shop, raw_texts=raw_texts, job_id=job_id)
    logger.info("[BrandIngest] async_accepted rid=%s shop=%s job_id=%s", rid, shop, job_id)
    return {"status": "accepted", "job_id": job_id}


@router.post("/api/onboarding/brand-soul")
async def onboarding_brand_soul_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Onboarding entrypoint for Brand Soul wizard.
    Delegates to the async ingestion pipeline.
    """
    return await brand_context_ingest_async_endpoint(
        request=request,
        background_tasks=background_tasks,
        db=db,
        shop=shop,
    )


@router.post("/api/admin/brand-context/extract-file")
async def brand_context_extract_file_endpoint(
    request: Request,
    shop: str = Depends(resolve_shop_domain),
):
    """
    Extract text from an uploaded file using GPT-4o-mini (vision).
    """
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        payload = BrandContextFileExtractRequest(**body)
    except ValidationError as e:
        logger.info("[BrandIngest] extract_invalid rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())

    try:
        text = extract_file_text(file_b64=payload.file_b64, mime_type=payload.mime_type)
    except Exception as e:
        logger.warning("[BrandIngest] extract_failed rid=%s shop=%s err=%s", rid, shop, e)
        raise HTTPException(status_code=500, detail="Failed to extract text from file")

    return {"status": "success", "text": text}


@router.get("/api/admin/brand-context/summary")
async def brand_context_summary_endpoint(
    request: Request,
    db: Session = Depends(get_db),
):
    shop_domain = (request.query_params.get("shop") or "").strip() or (
        request.headers.get("X-Shopify-Shop-Domain") or ""
    ).strip()
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    chunk_count = (
        db.query(StoreContext).filter(StoreContext.shop_id == shop_domain).count()
    )
    return {
        "shop": shop_domain,
        "summary": str(getattr(shop, "brand_context_summary", "") or "").strip(),
        "updated_at": (
            getattr(shop, "brand_context_updated_at", None).isoformat()
            if getattr(shop, "brand_context_updated_at", None)
            else None
        ),
        "chunk_count": int(chunk_count or 0),
    }


@router.get("/api/admin/brand-context/status")
async def brand_context_status_endpoint(
    request: Request,
    db: Session = Depends(get_db),
):
    shop_domain = (request.query_params.get("shop") or "").strip() or (
        request.headers.get("X-Shopify-Shop-Domain") or ""
    ).strip()
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    return {
        "shop": shop_domain,
        "status": getattr(shop, "brand_context_status", None) or "idle",
        "job_id": getattr(shop, "brand_context_job_id", None),
        "last_error": getattr(shop, "brand_context_last_error", None),
        "summary": str(getattr(shop, "brand_context_summary", "") or "").strip(),
        "updated_at": (
            getattr(shop, "brand_context_updated_at", None).isoformat()
            if getattr(shop, "brand_context_updated_at", None)
            else None
        ),
    }


@router.get("/api/admin/reinstall-path")
async def reinstall_pathfinder(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Internal helper for the UI to decide where a (re)install should land.

    Paths:
    - Paid + grace active (access_expires_at in future): /app (Home) and keep prior plan active
    - Paid + expired: /app/pricing?returning_paid=1
    - Free: /app/dashboard if credits>0 else /app/pricing
    """
    shop_domain = (request.query_params.get("shop") or "").strip()
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    ctx = get_shop_quota_context(db, shop_domain)
    if not ctx:
        # Unknown shop: treat as Free new install
        return {"redirect_to": "/app/dashboard", "reason": "new_shop"}

    shop: Shop = ctx["shop"]
    last_plan = str(ctx.get("last_plan_name") or "").strip() or "Free"
    grace_active = bool(ctx.get("grace_active"))
    expired_paid = bool(ctx.get("expired_paid"))
    access_expires_at = ctx.get("access_expires_at")

    def _is_paid(name: str) -> bool:
        return str(name or "").strip().lower() in ("basic", "standard", "pro")

    # Always mark the DB row active on reinstall/login. Token is handled by the UI token sync.
    try:
        shop.is_active = True
        db.add(shop)
        db.commit()
        db.refresh(shop)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    if _is_paid(last_plan):
        if bool(ctx.get("grace_mode")):
            # Grace: keep their paid tier for gating
            try:
                shop.current_plan_name = last_plan
                db.add(shop)
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
            return {
                "redirect_to": "/app",
                "reason": "paid_grace_active",
                "access_expires_at": access_expires_at.isoformat() if access_expires_at else None,
            }

        # Expired paid: force them back to pricing and prevent fallback to Free.
        try:
            shop.current_plan_name = None
            db.add(shop)
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {
            "redirect_to": "/app/pricing?returning_paid=1",
            "reason": "paid_expired",
            "access_expires_at": access_expires_at.isoformat() if access_expires_at else None,
        }

    # Free path: preserve lifetime credits
    remaining = int(getattr(shop, "lifetime_rewrites_remaining", 0) or 0)
    if remaining > 0:
        # Ensure plan names are initialized for legacy rows
        try:
            if not (getattr(shop, "last_plan_name", None) or "").strip():
                shop.last_plan_name = "Free"
            if not (getattr(shop, "current_plan_name", None) or "").strip():
                shop.current_plan_name = "Free"
            db.add(shop)
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {"redirect_to": "/app/dashboard", "reason": "free_with_credits"}
    return {"redirect_to": "/app/pricing", "reason": "free_no_credits"}


@router.post("/api/admin/sync-token")
async def sync_token(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Accepts a Shopify access token from the UI after its OAuth completes,
    and stores it in the API DB so proxy endpoints have credentials.
    Protected by a shared secret header.
    """
    if not TOKEN_SYNC_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfigured: TOKEN_SYNC_SECRET not set")

    provided_secret = request.headers.get("X-Token-Sync-Secret")
    if not provided_secret or not secrets.compare_digest(provided_secret, TOKEN_SYNC_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    shop = payload.get("shop")
    access_token = payload.get("access_token")
    token_type = payload.get("token_type", "offline") # Default to offline if not specified
    force = bool(payload.get("force", False))

    if not shop or not access_token:
        raise HTTPException(status_code=400, detail="Missing shop or access_token")

    logger.info("[SyncToken] start rid=%s shop=%s type=%s force=%s", _rid(request), shop, token_type, force)
    store_shop_access_token(db, shop, access_token, token_type=token_type, force=force)
    return Response(status_code=204)

@router.post("/webhooks/subscription-activated")
async def handle_subscription_activated(
    request: Request,
    db: Session = Depends(get_db)
):
    await verify_webhook_signature(request)
    logger.info(
        "[Webhook] subscription_activated rid=%s shop=%s webhook_id=%s",
        _rid(request),
        (request.headers.get("X-Shopify-Shop-Domain") or "").strip() or "-",
        (request.headers.get("X-Shopify-Webhook-Id") or "").strip() or "-",
    )
    
    try:
        payload = await request.json()
        # Shopify standard webhook for APP_SUBSCRIPTIONS_UPDATE
        # Check for both custom payload and standard Shopify payload
        app_subscription = payload.get('app_subscription', {})
        status = "ACTIVE"
        
        if app_subscription:
            # Standard Shopify webhook
            shop_domain = request.headers.get("X-Shopify-Shop-Domain")
            plan_name = app_subscription.get('name')
            status = str(app_subscription.get('status') or "").strip() or "ACTIVE"
        else:
            # Fallback for manual/custom triggers
            shop_domain = payload.get('myshopify_domain')
            plan_name = payload.get('billing_plan') 
            status = "ACTIVE"
        
        if not shop_domain or not plan_name:
            logger.warning("Webhook payload missing shop domain or plan name")
            return Response(status_code=200)

        # Shopify subscription names can differ from our internal plan names (e.g. promo/annual SKUs).
        # Canonicalize to our DB plan names so quota + gating stays stable.
        raw_plan_name = str(plan_name or "").strip()
        pn = raw_plan_name.lower()
        try:
            import re

            def has_word(w: str) -> bool:
                return re.search(rf"\b{re.escape(w)}\b", pn) is not None
        except Exception:
            # Extremely defensive fallback; prefer not to match "promo" as "pro"
            def has_word(w: str) -> bool:  # type: ignore[no-redef]
                return f" {w} " in f" {pn} "

        if has_word("basic"):
            plan_name = "Basic"
        elif has_word("standard"):
            plan_name = "Standard"
        elif has_word("pro"):
            plan_name = "Pro"
        elif has_word("free"):
            plan_name = "Free"
        else:
            plan_name = raw_plan_name

        plan = get_plan_by_name(db, plan_name)
        if not plan:
            logger.warning(f"Webhook received for unknown plan: raw={raw_plan_name} canonical={plan_name}")
            return Response(status_code=200)

        def _tier_rank(name: str | None) -> int:
            n = str(name or "").strip().lower()
            if n == "pro":
                return 3
            if n == "standard":
                return 2
            if n == "basic":
                return 1
            return 0

        # Persist paid-cycle expiry + last/current plan on the Shop row.
        # This enables a "grace period" after uninstall, even if Shopify cancels the subscription immediately.
        try:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
            downgrade_scheduled = False
            if shop_rec:
                shop_rec.is_active = True
                shop_rec.last_shopify_subscription_status = str(status or "").strip() or None

                current_name = (getattr(shop_rec, "current_plan_name", None) or "").strip() or str(getattr(plan, "name", "") or "").strip()
                current_rank = _tier_rank(current_name)
                new_rank = _tier_rank(plan.name)

                # Non-active status means Shopify indicates cancellation/expiry. We schedule a downgrade to Free
                # at the end of the already-paid window (access_expires_at).
                if app_subscription and str(status or "").strip().upper() != "ACTIVE":
                    shop_rec.last_plan_change_type = "cancel"
                    shop_rec.last_plan_change_at = now
                    shop_rec.pending_plan_name = "Free"
                    # Honor existing prepaid window; if missing, be conservative and downgrade soon.
                    eff = getattr(shop_rec, "access_expires_at", None) or (now + timedelta(days=1))
                    shop_rec.pending_plan_effective_at = eff
                else:
                    # ACTIVE update: can be upgrade or downgrade.
                    if new_rank < current_rank:
                        # Downgrade: schedule at end of current paid cycle (do not change current_plan_name yet).
                        shop_rec.last_plan_change_type = "downgrade"
                        shop_rec.last_plan_change_at = now
                        shop_rec.pending_plan_name = plan.name
                        eff = getattr(shop_rec, "access_expires_at", None) or (now + timedelta(days=30))
                        shop_rec.pending_plan_effective_at = eff
                        downgrade_scheduled = True
                    else:
                        # Upgrade or same tier: apply immediately.
                        shop_rec.last_plan_change_type = "upgrade" if new_rank > current_rank else "none"
                        shop_rec.last_plan_change_at = now
                        shop_rec.current_plan_name = plan.name
                        shop_rec.last_plan_name = plan.name
                        shop_rec.pending_plan_name = None
                        shop_rec.pending_plan_effective_at = None
                        # Manual plan change/activation means it's NOT a reinstall grace display state.
                        shop_rec.last_uninstalled_at = None
                        # For paid plans, set a hard expiry window (30 days from activation).
                        # For Free, clear any paid expiry.
                        if str(plan.name or "").strip().lower() in ("basic", "standard", "pro"):
                            shop_rec.access_expires_at = now + timedelta(days=30)
                        else:
                            shop_rec.access_expires_at = None
                db.add(shop_rec)
                db.commit()
        except Exception as e:
            logger.warning(f"[Webhook] unable to persist shop plan/expiry for {shop_domain}: {e}")
            try:
                db.rollback()
            except Exception:
                pass

        # ACTION: Explicitly update the User's plan in DB to ensure immediate effect
        # Wrap in try/except to avoid failing when test DB tables are absent.
        try:
            user = get_user_by_username(db, shop_domain)
            if user:
                # On downgrade/cancel we do NOT change user.plan_id until the downgrade is effective.
                if str(status or "").strip().upper() == "ACTIVE" and not downgrade_scheduled:
                    logger.info(f"Updating plan for {shop_domain} to {plan.name} (ID: {plan.id})")
                    user.plan_id = plan.id
                    db.commit()
                    db.refresh(user)

            # Also reset product rewrite usage when a plan changes (new billing cycle anchor)
            try:
                shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
                if shop_rec:
                    from datetime import datetime, timedelta, timezone
                    now = datetime.now(timezone.utc)
                    shop_rec.monthly_rewrites_used = 0
                    shop_rec.monthly_cost_accumulated = 0
                    shop_rec.fair_use_last_notified_at = None
                    shop_rec.reset_anchor_date = now
                    shop_rec.next_reset_date = now + timedelta(days=30)
                    db.add(shop_rec)
                    db.commit()
            except Exception as e:
                logger.warning(f"Shop rewrite reset skipped for {shop_domain}: {e}")
        except Exception as e:
            logger.warning(f"Plan update skipped for {shop_domain}: {e}")

        onboarding_req = OnboardingRequest(
            username=shop_domain,
            plan_id=plan.id,
            email=payload.get('email') or f"contact@{shop_domain}"
        )
        
        try:
            onboard_user(db, onboarding_req)
            logger.info(f"Webhook successfully onboarded user: {shop_domain}")
        except HTTPException as e:
            if e.status_code == 409:
                logger.info(f"User {shop_domain} already exists. Skipping creation.")
            else:
                logger.error(f"Onboarding error processing webhook: {e.detail}")
        except Exception as e:
            logger.error(f"Unexpected error processing webhook: {e}")

    except Exception as e:
        logger.error(f"Error parsing webhook payload: {e}")
        return Response(status_code=200)

    return Response(status_code=200)

@router.post("/api/webhooks/compliance")
async def compliance_webhooks(request: Request, db: Session = Depends(get_db)):
    """
    Mandatory Shopify GDPR webhooks endpoint.

    Requirements:
    - Extract X-Shopify-Topic immediately
    - Verify webhook HMAC using RAW request body bytes
    - Return 200 OK quickly (avoid retries)
    - Log to security.log for audit
    """
    # Requirement 1: topic first (no JSON parsing yet)
    topic = (request.headers.get("X-Shopify-Topic") or "").strip().lower()
    shop_domain = (request.headers.get("X-Shopify-Shop-Domain") or "").strip()
    webhook_id = (request.headers.get("X-Shopify-Webhook-Id") or "").strip()

    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")

    # Requirement 4: reject immediately if verification fails
    try:
        from src.main.security.security import verify_shopify_webhook, SHOPIFY_API_SECRET
        verify_shopify_webhook(raw_body=raw_body, hmac_header=hmac_header, api_secret=SHOPIFY_API_SECRET)
    except HTTPException:
        # Keep audit trail even for rejected requests (do not log raw body)
        security_logger.warning(
            f"[GDPR] REJECTED topic={topic or '<missing>'} shop={shop_domain or '<missing>'} "
            f"webhook_id={webhook_id or '<missing>'} body_len={len(raw_body)}"
        )
        raise

    # Audit log (success path) — avoid storing PII; do not log payload contents
    security_logger.info(
        f"[GDPR] ACCEPTED topic={topic or '<missing>'} shop={shop_domain or '<missing>'} "
        f"webhook_id={webhook_id or '<missing>'} body_len={len(raw_body)}"
    )

    # Requirement 2: keep handlers lightweight and always return 200 fast.
    # We do best-effort DB cleanup for shop/redact; other topics are acknowledgements.
    try:
        if topic == "customers/data_request":
            security_logger.info(
                f"[GDPR] customers/data_request acknowledged shop={shop_domain or '<missing>'} "
                f"(no customer PII stored by Cross-Border AI)"
            )
            return {"status": "ok", "message": "No customer personal data stored."}

        if topic == "customers/redact":
            security_logger.info(
                f"[GDPR] customers/redact acknowledged shop={shop_domain or '<missing>'} "
                f"(no customer-linked records to delete)"
            )
            return {"status": "ok", "message": "Customer data redaction acknowledged."}

        if topic == "shop/redact":
            # 48 hours after uninstall: delete all merchant-related records (best-effort).
            # NOTE: We do not log request payload; shop_domain is from header.
            from src.main.db.db_models import Shop, User, UsageRecord

            if shop_domain:
                user = db.query(User).filter(User.username == shop_domain).first()
                if user:
                    # Delete usage records for this merchant
                    db.query(UsageRecord).filter(UsageRecord.user_id == user.id).delete(synchronize_session=False)
                    db.delete(user)

                shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
                if shop_rec:
                    db.delete(shop_rec)

                db.commit()
                security_logger.info(f"[GDPR] shop/redact deleted merchant records shop={shop_domain}")
            else:
                security_logger.warning("[GDPR] shop/redact missing X-Shopify-Shop-Domain header")

            return {"status": "ok", "message": "Shop data redaction processed."}

        # Unknown/other: acknowledge to avoid retries
        security_logger.info(f"[GDPR] unknown_topic acknowledged topic={topic or '<missing>'} shop={shop_domain or '<missing>'}")
        return {"status": "ok", "message": "Webhook acknowledged."}
    except Exception as e:
        # Never block Shopify retries with long work; log and ACK.
        try:
            db.rollback()
        except Exception:
            pass
        security_logger.error(
            f"[GDPR] handler_error topic={topic or '<missing>'} shop={shop_domain or '<missing>'} err={e}"
        )
        return {"status": "ok", "message": "Webhook acknowledged."}


@router.post("/webhooks/app/uninstalled")
async def handle_app_uninstalled(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle app/uninstalled webhook.
    Keep this handler very fast to avoid Shopify timeouts.
    """
    await verify_webhook_signature(request)
    try:
        payload = await request.json()
        shop_domain = payload.get("myshopify_domain") or request.headers.get("X-Shopify-Shop-Domain")

        logger.info("[Webhook] app_uninstalled rid=%s shop=%s", _rid(request), shop_domain or "-")

        if shop_domain:
            # IMPORTANT: do not delete Shop rows on uninstall.
            # We need to preserve lifetime credits for Free plan reinstalls.
            try:
                shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
                if shop_rec:
                    # Persist last_plan_name so we can route reinstalls correctly.
                    # Prefer the Shop row's current_plan_name; fall back to the User's plan if available.
                    try:
                        current = (getattr(shop_rec, "current_plan_name", None) or "").strip()
                        if not current:
                            user = get_user_by_username(db, shop_domain)
                            if user and getattr(user, "plan", None):
                                current = (getattr(user.plan, "name", None) or "").strip()
                        if current:
                            shop_rec.last_plan_name = current
                    except Exception:
                        pass

                    shop_rec.is_active = False
                    try:
                        from datetime import datetime, timezone
                        shop_rec.last_uninstalled_at = datetime.now(timezone.utc)
                    except Exception:
                        pass
                    # Token is invalid after uninstall; keep row but clear token.
                    shop_rec.access_token = ""
                    db.add(shop_rec)
                    db.commit()
            except Exception as e:
                logger.warning(f"Unable to deactivate shop record for {shop_domain}: {e}")
                db.rollback()

    except Exception as e:
        logger.error(f"Error handling app/uninstalled webhook: {e}")

    # Always return 200 quickly to avoid retries/timeouts
    return Response(status_code=200)


@router.post("/webhooks/app/install")
async def handle_app_install(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    App install (or reinstall) webhook.

    Requirements:
    - If Shop exists: set is_active=True and keep lifetime_rewrites_remaining (do NOT reset).
    - Else: create Shop with lifetime_rewrites_remaining=10.
    """
    await verify_webhook_signature(request)
    shop_domain = (request.headers.get("X-Shopify-Shop-Domain") or "").strip()
    try:
        payload = await request.json()
        shop_domain = (payload.get("myshopify_domain") or shop_domain or "").strip()
    except Exception:
        payload = {}

    if not shop_domain:
        return Response(status_code=200)

    logger.info("[Webhook] app_install rid=%s shop=%s", _rid(request), shop_domain)

    try:
        shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
        if shop_rec:
            previously_inactive = not bool(getattr(shop_rec, "is_active", True))
            shop_rec.is_active = True
            # Preserve existing lifetime credits (critical).
            # Also preserve monthly counters; monthly reset is handled elsewhere.
            if previously_inactive:
                shop_rec.welcome_back_pending = True
            db.add(shop_rec)
            db.commit()
            db.refresh(shop_rec)
        else:
            # New shop: create a row with 10 lifetime credits.
            shop_rec = Shop(
                domain=shop_domain,
                access_token="",
                monthly_rewrites_used=0,
                lifetime_rewrites_remaining=10,
                is_active=True,
                welcome_back_pending=False,
            )
            db.add(shop_rec)
            db.commit()
            db.refresh(shop_rec)

        # Ensure a User row exists (billing/quota identity). Default to Free plan.
        user = get_user_by_username(db, shop_domain)
        if not user:
            free_plan = db.query(Plan).filter(Plan.name == "Free").first()
            if free_plan:
                user = User(username=shop_domain, email=None, plan_id=free_plan.id)
                db.add(user)
                db.commit()
    except Exception as e:
        logger.warning(f"[Webhook] app_install failed shop={shop_domain}: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    return Response(status_code=200)

@router.get("/api/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    params = dict(request.query_params)
    
    try:
        verify_shopify_redirect(params)
    except HTTPException as e:
        logger.error(f"OAuth redirect verification failed: {e.detail}")
        raise

    code = params.get("code")
    shop = params.get("shop")
    host = params.get("host")

    if not code or not shop:
        raise HTTPException(status_code=400, detail="Missing code or shop parameter")

    logger.info(f"[OAuth Callback] Starting token exchange for shop={shop}, host={host}")

    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code
    }

    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, json=payload)
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            
            logger.info(f"Successfully exchanged token for shop: {shop}")
            logger.info(f"Auth callback params: host={host}, timestamp={params.get('timestamp')}")
            store_shop_access_token(db, shop, access_token)
            
            # Redirect to the Remix UI's login route to ensure the UI also authenticates
            # The Remix app will handle the second half of the handshake and then load the embedded app
            ui_login_url = f"{SHOPIFY_UI_URL}/auth/login?shop={shop}"
            if host:
                ui_login_url += f"&host={host}"
            logger.info(f"Redirecting to UI login for secondary handshake: {ui_login_url}")
            return RedirectResponse(url=ui_login_url)

    except httpx.HTTPStatusError as e:
        logger.error(f"Token exchange failed: {e.response.text}")
        raise HTTPException(status_code=400, detail="Failed to exchange access token")
    except Exception as e:
        logger.error(f"Unexpected error during token exchange: {e}")
        raise HTTPException(status_code=500, detail="Internal OAuth Error")


# ==============================================================================
#  4. SHOP LOCALES ENDPOINT
# ==============================================================================
@router.get("/api/proxy/shop/locales")
async def get_shop_locales(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(verify_shopify_proxy_request),
):
    """
    Fetches the enabled locales for the shop.
    Delegates to Core layer.
    """
    rid = _rid(request)
    logger.info("[Locales] start rid=%s shop=%s", rid, shop)
    resp = await fetch_shop_locales(db, shop)
    try:
        logger.info(
            "[Locales] done rid=%s shop=%s locales=%s",
            rid,
            shop,
            len(resp.get("locales", [])) if isinstance(resp, dict) else None,
        )
    except Exception:
        pass
    return resp

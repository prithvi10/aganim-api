"""
Shopify Admin Routes

Handles admin UI endpoints including usage, brand context, and onboarding.
"""

import json
from fastapi import APIRouter, HTTPException, Depends, Request, Response, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.main.api.models import BrandContextIngestRequest, BrandContextFileExtractRequest
from src.main.db.database import get_db, SessionLocal
from src.main.db.db_models import Shop, StoreContext
from src.main.api.validation import validate_shop_and_quota
from src.main.security.security import verify_shopify_session
from src.main.services.brand_ingest_service import ingest_brand_context, scrape_urls, extract_file_text
from src.main.config.configs import PROMO_PRICING_ENABLED
from src.main.logging.logger import get_logger

from .shared import resolve_shop_domain, _rid

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Admin Info Endpoint
# =============================================================================

@router.get("/api/admin/me")
async def get_admin_info(
    request: Request,
    shop: str = Depends(verify_shopify_session)
):
    logger.info("[AdminMe] rid=%s shop=%s", _rid(request), shop)
    return {"status": "authenticated", "shop": shop, "message": "Welcome to the Admin API"}


# =============================================================================
# Usage Endpoint
# =============================================================================

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


# =============================================================================
# Onboarding Endpoints
# =============================================================================

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


# =============================================================================
# Brand Context Endpoints
# =============================================================================

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

        result = ingest_brand_context(db, shop_id=shop_id, raw_texts=raw_texts)

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


@router.options("/api/admin/brand-context/ingest-async")
async def brand_context_ingest_async_preflight():
    # Explicit preflight handler to avoid proxy/CORS edge cases.
    return Response(status_code=204)


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
    brand_context = getattr(shop, "brand_context", None) or {}
    if isinstance(brand_context, str):
        try:
            brand_context = json.loads(brand_context)
        except Exception:
            brand_context = {}
    if not isinstance(brand_context, dict):
        brand_context = {}

    # Backward compatibility mapping:
    # If using new nested shape (en/ja keys), map them to top-level fields for UI.
    en = brand_context.get("en") or {}
    ja = brand_context.get("ja") or {}
    
    summary_en = str(en.get("clean_text") or brand_context.get("summary_en") or "").strip()
    summary_ja = str(ja.get("clean_text") or brand_context.get("summary_ja") or "").strip()
    summary = summary_en or summary_ja
    
    key_facts_en = (
        (en.get("pillars") if isinstance(en.get("pillars"), list) else []) or
        (brand_context.get("key_facts_en") if isinstance(brand_context.get("key_facts_en"), list) else [])
    )
    key_facts_ja = (
        (ja.get("pillars") if isinstance(ja.get("pillars"), list) else []) or
        (brand_context.get("key_facts_ja") if isinstance(brand_context.get("key_facts_ja"), list) else [])
    )
    key_facts = key_facts_en or key_facts_ja
    
    return {
        "shop": shop_domain,
        "summary": summary,
        "summary_en": summary_en,
        "summary_ja": summary_ja,
        "key_facts": key_facts,
        "key_facts_en": key_facts_en,
        "key_facts_ja": key_facts_ja,
        "brand_context": brand_context,
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

    brand_context = getattr(shop, "brand_context", None) or {}
    if isinstance(brand_context, str):
        try:
            brand_context = json.loads(brand_context)
        except Exception:
            brand_context = {}
    if not isinstance(brand_context, dict):
        brand_context = {}

    # Backward compatibility mapping:
    # If using new nested shape (en/ja keys), map them to top-level fields for UI.
    en = brand_context.get("en") or {}
    ja = brand_context.get("ja") or {}
    
    summary_en = str(en.get("clean_text") or brand_context.get("summary_en") or "").strip()
    summary_ja = str(ja.get("clean_text") or brand_context.get("summary_ja") or "").strip()
    summary = summary_en or summary_ja
    
    key_facts_en = (
        (en.get("pillars") if isinstance(en.get("pillars"), list) else []) or
        (brand_context.get("key_facts_en") if isinstance(brand_context.get("key_facts_en"), list) else [])
    )
    key_facts_ja = (
        (ja.get("pillars") if isinstance(ja.get("pillars"), list) else []) or
        (brand_context.get("key_facts_ja") if isinstance(brand_context.get("key_facts_ja"), list) else [])
    )
    key_facts = key_facts_en or key_facts_ja
    
    return {
        "shop": shop_domain,
        "status": getattr(shop, "brand_context_status", None) or "idle",
        "job_id": getattr(shop, "brand_context_job_id", None),
        "last_error": getattr(shop, "brand_context_last_error", None),
        "summary": summary,
        "summary_en": summary_en,
        "summary_ja": summary_ja,
        "key_facts": key_facts,
        "key_facts_en": key_facts_en,
        "key_facts_ja": key_facts_ja,
        "brand_context": brand_context,
        "updated_at": (
            getattr(shop, "brand_context_updated_at", None).isoformat()
            if getattr(shop, "brand_context_updated_at", None)
            else None
        ),
    }

"""
Shopify Admin Routes

Handles admin UI endpoints including usage, brand context, and onboarding.
"""

import json
from fastapi import APIRouter, HTTPException, Depends, Request, Response, BackgroundTasks, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.ecommerce.api.models import BrandContextIngestRequest, BrandContextFileExtractRequest, BrandContextUpdateRequest
from src.shared.db.database import get_db, SessionLocal
from src.ecommerce.db.models import Shop, StoreContext
from src.ecommerce.api.validation import validate_shop_and_quota, validate_feature_access
from src.ecommerce.plans.entitlements import get_entitlements
from src.ecommerce.db.transactions import get_feature_usage
from src.shared.security.security import verify_shopify_session
from src.ecommerce.services.brand_ingest_service import (
    ingest_brand_context,
    ingest_brand_context_with_intelligence,
    scrape_urls,
    extract_file_text,
)
from src.ecommerce.services.intelligence_extractor import IntelligenceExtractorService
from src.agentic_core.llm.llm_service import LLMService
from src.agentic_core.rag.rag_service import RAGService
from datetime import datetime, timezone
from src.ecommerce.config.configs import PROMO_PRICING_ENABLED
from src.shared.logging.logger import get_logger

from src.ecommerce.db.models import User, OutreachLog
from src.ecommerce.db.transactions import _fetch_shop_owner_email, get_shop_access_token
from src.ecommerce.services.email_templates import welcome_email
from src.ecommerce.services.email_service import send_email
from src.ecommerce.config.shopify_config import SHOPIFY_UI_URL

from .shared import resolve_shop_domain, _rid

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Complete Install — fetch email + send welcome (called by UI after auth settles)
# =============================================================================

_INSTALL_RETRY_DELAYS = [2.0, 3.0]


def _complete_install_sync(shop_domain: str) -> None:
    """Background task: fetch shop email with retries + send welcome email.

    Runs in its own DB session so the request handler can return immediately.
    """
    import asyncio
    import time

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == shop_domain).first()
        if not user:
            return

        if not user.email:
            access_token = get_shop_access_token(db, shop_domain)
            owner_email = None
            if access_token:
                owner_email = _fetch_shop_owner_email(shop_domain, access_token)
                if not owner_email:
                    for delay in _INSTALL_RETRY_DELAYS:
                        logger.info("[CompleteInstall] retry in %.0fs for %s", delay, shop_domain)
                        time.sleep(delay)
                        # Re-read token in case sync-token updated it (multi-instance race)
                        access_token = get_shop_access_token(db, shop_domain)
                        if not access_token:
                            break
                        owner_email = _fetch_shop_owner_email(shop_domain, access_token)
                        if owner_email:
                            break
            if owner_email:
                existing_user = (
                    db.query(User)
                    .filter(User.email == owner_email, User.id != user.id)
                    .first()
                )
                if existing_user:
                    logger.warning(
                        "[CompleteInstall] email %s already belongs to user id=%s (%s); "
                        "skipping assignment for %s",
                        owner_email, existing_user.id, existing_user.username, shop_domain,
                    )
                else:
                    try:
                        user.email = owner_email
                        db.commit()
                        logger.info("[CompleteInstall] backfilled email for %s: %s", shop_domain, owner_email)
                    except Exception:
                        db.rollback()
                        logger.warning(
                            "[CompleteInstall] IntegrityError setting email %s for %s — skipping",
                            owner_email, shop_domain,
                        )

        if not user.email:
            logger.info("[CompleteInstall] still no email for %s — skipping welcome", shop_domain)
            return

        existing = (
            db.query(OutreachLog)
            .filter(OutreachLog.recipient_shop == shop_domain, OutreachLog.subject.ilike("%welcome%"))
            .first()
        )
        if existing:
            return

        try:
            subj, html_body, text_body = welcome_email(
                merchant_name=shop_domain,
                app_url=SHOPIFY_UI_URL,
            )
            asyncio.run(send_email(
                to=user.email,
                subject=subj,
                html_body=html_body,
                text_body=text_body,
            ))
            log = OutreachLog(
                recipient_email=user.email,
                recipient_shop=shop_domain,
                subject=subj,
                body=text_body[:500],
                status="sent",
            )
            db.add(log)
            db.commit()
            logger.info("[CompleteInstall] welcome email sent to %s for %s", user.email, shop_domain)
        except Exception as e:
            logger.warning("[CompleteInstall] welcome email failed for %s: %s", shop_domain, e)
    except Exception as e:
        logger.warning("[CompleteInstall] background task failed for %s: %s", shop_domain, e)
    finally:
        db.close()


@router.post("/api/admin/complete-install", status_code=204)
async def complete_install(
    request: Request,
    bg: BackgroundTasks,
):
    """
    Called by the UI after OAuth + token sync are fully settled.
    Enqueues a background task that fetches the shop owner email from
    Shopify (with retries for token propagation delay) and sends a
    welcome email on first install.  Returns 204 immediately.
    """
    shop_domain = request.query_params.get("shop", "").strip()
    if not shop_domain:
        return Response(status_code=204)

    logger.info("[CompleteInstall] start shop=%s", shop_domain)
    bg.add_task(_complete_install_sync, shop_domain)
    return Response(status_code=204)


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
    
    effective_plan = (auth_context.get("effective_plan_name") or plan.name)
    ent = get_entitlements(effective_plan)

    # Build per-feature usage summary for the frontend
    fu = {}
    try:
        fu = get_feature_usage(db, shop.domain)
    except Exception:
        pass

    def _usage_pair(feature: str, limit_key: str = "product_limit") -> dict:
        used = fu.get(feature, 0)
        limit = int(ent.get(limit_key, 0))
        return {"used": used, "limit": limit}

    feature_usage = {
        "rewriter": _usage_pair("rewriter"),
        "seo": _usage_pair("seo"),
        "marketing": _usage_pair("marketing"),
        "price_scout": _usage_pair("price_scout"),
        "missions": {
            "used": (
                max(0, int(ent.get("mission_limit", 3)) - int(getattr(shop, "lifetime_missions_remaining", 0) or 0))
                if ent.get("mission_limit_type") == "lifetime"
                else int(getattr(shop, "monthly_missions_used", 0) or 0)
            ),
            "limit": int(ent.get("mission_limit", 0)),
        },
        "image_generation": {
            "used": (
                max(0, int(ent.get("image_generation_limit", 5)) - int(getattr(shop, "lifetime_image_credits_remaining", 0) or 0))
                if ent.get("image_limit_type") == "lifetime"
                else int(getattr(shop, "monthly_image_generations_used", 0) or 0)
            ),
            "limit": int(ent.get("image_generation_limit", 0)),
        },
    }

    return {
        "plan_name": effective_plan,
        "monthly_rewrites_used": rewrites_used,
        "rewrite_limit": rewrite_limit,
        "next_reset_date": next_reset.isoformat() if next_reset else None,
        "billing_cycle_type": billing_cycle_type,
        "lifetime_rewrites_remaining": lifetime_remaining if billing_cycle_type == "lifetime" else None,
        "current_usage": rewrites_used,
        "monthly_token_quota": rewrite_limit,
        "product_limit": plan.product_limit,
        "max_locales": plan.max_locales,
        "features_json": plan.features_json,
        "is_pro": plan.name in ("Standard", "Pro"),
        "welcome_back": welcome_back,
        "access_expires_at": (auth_context.get("access_expires_at").isoformat() if auth_context.get("access_expires_at") else None),
        "grace_active": bool(auth_context.get("grace_active")),
        "grace_mode": bool(auth_context.get("grace_mode")),
        "last_plan_name": auth_context.get("last_plan_name"),
        "last_uninstalled_at": (auth_context.get("last_uninstalled_at").isoformat() if auth_context.get("last_uninstalled_at") else None),
        "promo_pricing_enabled": bool(PROMO_PRICING_ENABLED),
        "is_onboarding_finished": bool(getattr(shop, "is_onboarding_finished", False)),
        "onboarding_step": int(getattr(shop, "onboarding_step", 0) or 0),
        "effective_plan_name": auth_context.get("effective_plan_name") or (getattr(shop, "current_plan_name", None) or plan.name),
        "current_plan_name": getattr(shop, "current_plan_name", None),
        "pending_plan_name": getattr(shop, "pending_plan_name", None),
        "pending_plan_effective_at": (getattr(shop, "pending_plan_effective_at", None).isoformat() if getattr(shop, "pending_plan_effective_at", None) else None),
        "last_plan_change_type": getattr(shop, "last_plan_change_type", None),
        "last_plan_change_at": (getattr(shop, "last_plan_change_at", None).isoformat() if getattr(shop, "last_plan_change_at", None) else None),
        # --- New plan-gating fields ---
        "entitlements": ent,
        "feature_usage": feature_usage,
        "ui_language": getattr(shop, "ui_language", "en") or "en",
        "default_target_locale": getattr(shop, "default_target_locale", "en") or "en",
    }


# =============================================================================
# UI Language Preference
# =============================================================================

_ALLOWED_UI_LANGUAGES = {"en", "ja"}


@router.put("/api/admin/ui-language")
async def update_ui_language(
    request: Request,
    db: Session = Depends(get_db),
):
    """Persist the merchant's UI language preference (en or ja)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    shop_domain = str(body.get("shop") or "").strip()
    ui_language = str(body.get("ui_language") or "").strip().lower()

    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop")
    if ui_language not in _ALLOWED_UI_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"ui_language must be one of {_ALLOWED_UI_LANGUAGES}")

    shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop_rec:
        raise HTTPException(status_code=404, detail="Shop not found")

    shop_rec.ui_language = ui_language
    db.add(shop_rec)
    db.commit()

    logger.info("[UiLang] shop=%s lang=%s", shop_domain, ui_language)
    return {"ui_language": ui_language}


# =============================================================================
# Default Target Locale Preference
# =============================================================================

from src.ecommerce.config.configs import LOCALE_PERSONA_MAP

_ALLOWED_TARGET_LOCALES = set(LOCALE_PERSONA_MAP.keys())


@router.put("/api/admin/default-target-locale")
async def update_default_target_locale(
    request: Request,
    db: Session = Depends(get_db),
):
    """Persist the merchant's default content target locale."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    shop_domain = str(body.get("shop") or "").strip()
    locale = str(body.get("locale") or "").strip()

    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop")
    if locale not in _ALLOWED_TARGET_LOCALES:
        raise HTTPException(
            status_code=400,
            detail=f"locale must be one of {sorted(_ALLOWED_TARGET_LOCALES)}",
        )

    shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop_rec:
        raise HTTPException(status_code=404, detail="Shop not found")

    shop_rec.default_target_locale = locale
    db.add(shop_rec)
    db.commit()

    logger.info("[DefaultLocale] shop=%s locale=%s", shop_domain, locale)
    return {"default_target_locale": locale}


# =============================================================================
# Plan Sync (From UI to API — called when Shopify has a subscription the DB
# doesn't know about, e.g. the subscription-activated webhook failed)
# =============================================================================

@router.post("/api/admin/sync-plan")
async def sync_plan(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Idempotent plan sync: the UI calls this when it detects the merchant
    already has an ACTIVE Shopify subscription that doesn't match the DB.
    Updates current_plan_name, last_plan_name, user.plan_id, and clears
    any stale pending-downgrade fields.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    shop_domain = str(payload.get("shop") or "").strip()
    plan_name = str(payload.get("plan_name") or "").strip()
    sub_status = str(payload.get("subscription_status") or "").strip().upper()

    if not shop_domain or not plan_name:
        raise HTTPException(status_code=400, detail="Missing shop or plan_name")

    logger.info("[SyncPlan] shop=%s plan=%s status=%s", shop_domain, plan_name, sub_status)

    from src.ecommerce.db.transactions import get_plan_by_name, get_user_by_username

    shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop_rec:
        logger.warning("[SyncPlan] shop not found: %s", shop_domain)
        return {"synced": False, "reason": "shop_not_found"}

    now = datetime.now(timezone.utc)

    # Only sync if the Shopify subscription is ACTIVE
    if sub_status != "ACTIVE":
        return {"synced": False, "reason": "not_active"}

    # Already in sync — nothing to do
    if (shop_rec.current_plan_name or "").strip() == plan_name:
        return {"synced": False, "reason": "already_synced"}

    # Update Shop record
    shop_rec.current_plan_name = plan_name
    shop_rec.last_plan_name = plan_name
    shop_rec.last_shopify_subscription_status = "ACTIVE"
    shop_rec.last_plan_change_type = "upgrade"
    shop_rec.last_plan_change_at = now
    # Clear any stale pending downgrade
    shop_rec.pending_plan_name = None
    shop_rec.pending_plan_effective_at = None
    # Reset usage counters for the new billing cycle
    shop_rec.monthly_rewrites_used = 0
    shop_rec.monthly_cost_accumulated = 0
    shop_rec.reset_anchor_date = now
    from datetime import timedelta
    shop_rec.next_reset_date = now + timedelta(days=30)
    # Extend access window
    shop_rec.access_expires_at = now + timedelta(days=30)
    db.add(shop_rec)

    # Update User.plan_id to match
    user = get_user_by_username(db, shop_domain)
    plan_obj = get_plan_by_name(db, plan_name)
    if user and plan_obj:
        user.plan_id = plan_obj.id
        db.add(user)

    try:
        db.commit()
        logger.info("[SyncPlan] ✅ synced %s → %s", shop_domain, plan_name)
    except Exception as e:
        db.rollback()
        logger.error("[SyncPlan] DB error: %s", e)
        raise HTTPException(status_code=500, detail="DB commit failed")

    return {"synced": True, "plan_name": plan_name}


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

    result = await ingest_brand_context_with_intelligence(db, shop_id=shop, raw_texts=raw_texts)

    # Set status to "ready" after the full pipeline (including intelligence) completes.
    # ingest_brand_context_with_intelligence uses set_status=False internally
    # to avoid a premature "ready" before intelligence extraction finishes.
    try:
        shop_record = db.query(Shop).filter(Shop.domain == shop).first()
        if shop_record:
            shop_record.brand_context_status = "ready"
            db.add(shop_record)
            db.commit()
    except Exception:
        pass

    logger.info(
        "[BrandIngest] done rid=%s shop=%s inserted=%s chunks=%s intel=%s",
        rid,
        shop,
        result.get("inserted"),
        result.get("chunk_count"),
        "yes" if result.get("strategic_intelligence") else "no",
    )
    return {"status": "success", **result}


def _run_brand_context_ingest(
    *,
    shop_id: str,
    raw_texts: list[dict],
    job_id: str,
) -> None:
    import asyncio
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(Shop.domain == shop_id).first()
        if shop:
            shop.brand_context_status = "running"
            shop.brand_context_last_error = None
            shop.brand_context_job_id = job_id
            db.add(shop)
            db.commit()

        # Run the async intelligence-aware ingestion from this sync background task
        result = asyncio.run(
            ingest_brand_context_with_intelligence(db, shop_id=shop_id, raw_texts=raw_texts)
        )

        logger.info(
            "[BrandIngest] background done shop=%s inserted=%s chunks=%s intel=%s",
            shop_id,
            result.get("inserted"),
            result.get("chunk_count"),
            "yes" if result.get("strategic_intelligence") else "no",
        )

        shop = db.query(Shop).filter(Shop.domain == shop_id).first()
        if shop:
            shop.brand_context_status = "ready"
            shop.brand_context_last_error = None
            shop.brand_context_job_id = job_id
            db.add(shop)
            db.commit()
    except Exception as e:
        logger.error("[BrandIngest] background failed shop=%s err=%s", shop_id, e)
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

    # Auto-heal stale "running" status.
    # If status is "running"/"accepted" but brand_context already has content and
    # the update timestamp is >5 min old, the background task likely crashed.
    current_status = getattr(shop, "brand_context_status", None) or "idle"
    if current_status in ("running", "accepted"):
        updated_at = getattr(shop, "brand_context_updated_at", None)
        has_content = bool(brand_context.get("en") or brand_context.get("ja") or brand_context.get("summary_en"))
        stale = False
        if updated_at:
            try:
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                stale = (datetime.now(timezone.utc) - updated_at).total_seconds() > 300
            except Exception:
                stale = True
        else:
            stale = True  # no updated_at at all
        if stale and has_content:
            logger.info("[BrandStatus] Auto-healing stale '%s' status for shop=%s", current_status, shop_domain)
            try:
                shop.brand_context_status = "ready"
                db.add(shop)
                db.commit()
            except Exception:
                db.rollback()

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


@router.put("/api/admin/brand-context/update")
async def brand_context_update_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Directly update the stored brand soul clean_text without re-running
    the ingestion pipeline. Zero LLM cost — pure DB write.
    """
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        payload = BrandContextUpdateRequest(**body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    if not shop_record:
        raise HTTPException(status_code=404, detail="Shop not found")

    brand_context = getattr(shop_record, "brand_context", None) or {}
    if isinstance(brand_context, str):
        try:
            brand_context = json.loads(brand_context)
        except Exception:
            brand_context = {}
    if not isinstance(brand_context, dict):
        brand_context = {}

    en = brand_context.get("en") or {}
    en["clean_text"] = payload.clean_text_en
    brand_context["en"] = en

    if payload.clean_text_ja is not None:
        ja = brand_context.get("ja") or {}
        ja["clean_text"] = payload.clean_text_ja
        brand_context["ja"] = ja

    from sqlalchemy.orm.attributes import flag_modified

    shop_record.brand_context = brand_context
    flag_modified(shop_record, "brand_context")
    shop_record.brand_context_updated_at = datetime.now(timezone.utc)
    db.add(shop_record)
    db.commit()

    logger.info("[BrandUpdate] direct_edit rid=%s shop=%s", rid, shop)
    return {
        "status": "success",
        "summary_en": str(en.get("clean_text") or ""),
        "summary_ja": str((brand_context.get("ja") or {}).get("clean_text") or ""),
    }


# =============================================================================
# Template Endpoints
# =============================================================================

@router.get("/api/templates")
async def list_templates_endpoint(
    request: Request,
    category: str = None,
    agent_type: str = None,
):
    """
    List available content templates.
    
    Args:
        category: Filter by category (product/marketing)
        agent_type: Filter by agent type (rewriter/marketing)
    
    Returns:
        List of template objects
    """
    from src.ecommerce.templates import (
        list_templates,
        TemplateCategory,
        AgentType,
    )
    
    category_enum = None
    if category:
        try:
            category_enum = TemplateCategory(category.lower())
        except ValueError:
            pass
    
    agent_type_enum = None
    if agent_type:
        try:
            agent_type_enum = AgentType(agent_type.lower())
        except ValueError:
            pass
    
    templates = list_templates(
        category=category_enum,
        agent_type=agent_type_enum,
    )
    
    return {
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "category": t.category.value,
                "agent_type": t.agent_type.value,
                "description": t.description,
                "output_format": t.output_format,
                "inputs": [
                    {
                        "name": inp.name,
                        "label": inp.label,
                        "required": inp.required,
                        "input_type": inp.input_type,
                        "description": inp.description,
                    }
                    for inp in t.inputs
                ],
            }
            for t in templates
        ]
    }


@router.post("/api/generate/{template_id:path}")
async def generate_content_endpoint(
    template_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Generate content using specified template.
    
    Args:
        template_id: Template ID (e.g., "product/blog-post", "marketing/email-launch")
        request: Request body with template inputs
    
    Returns:
        Generated content
    """
    from src.ecommerce.templates import get_template
    from src.ecommerce.state import MissionState
    from src.ecommerce.services.registry import ServiceRegistry
    
    # Get template
    template = get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    
    # Parse request body
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    # Build mission state
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=False)
    plan_name = auth_context.get("effective_plan_name") or "Free"

    state = MissionState(
        product_id=body.get("product_id", ""),
        shop_id=shop,
        plan_tier=plan_name,
        raw_input={
            "template_id": template_id,
            **body,  # Include all template inputs
        },
        db=db,
    )
    
    # Create services with db and shop for usage tracking
    services = ServiceRegistry.create_default(db=db, shop_domain=shop)
    services.rag = RAGService()
    
    # Route to appropriate agent
    if template.agent_type.value == "rewriter":
        from src.ecommerce.agents.rewriter import RewriterAgent
        agent = RewriterAgent(shop_id=shop, services=services)
    elif template.agent_type.value == "marketing":
        from src.ecommerce.agents.marketing import MarketingAgent
        agent = MarketingAgent(shop_id=shop, services=services)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {template.agent_type.value}")
    
    # Execute agent
    try:
        new_state = await agent.run(state)

        hero_url = None
        hero_eligible = {"product/blog-post", "product/collection", "product/landing-hero"}

        if template_id in hero_eligible:
            try:
                import json as _json
                import uuid as _uuid
                from src.ecommerce.services.hero_image_generator import HeroImageGenerator
                from src.ecommerce.services.r2_storage_service import R2StorageService
                from src.ecommerce.services.art_director import (
                    generate_visual_brief,
                    ImageStyle,
                    get_current_season,
                    get_season_props,
                )
                from src.ecommerce.agents.visual.prompts import (
                    build_styled_prompt,
                    build_blog_hero_from_brief,
                )

                image_style = body.get("image_style", "attractive")
                image_url = body.get("image_url", "")

                try:
                    style_enum = ImageStyle(image_style)
                except ValueError:
                    style_enum = ImageStyle.ATTRACTIVE

                # --- Blog-post path: use visual_brief from LLM output ---
                blog_visual_brief = None
                if template_id == "product/blog-post" and new_state.draft_content:
                    try:
                        blog_data = _json.loads(new_state.draft_content)
                        if isinstance(blog_data, dict) and "visual_brief" in blog_data:
                            blog_visual_brief = blog_data["visual_brief"]
                    except (ValueError, TypeError):
                        pass

                if blog_visual_brief:
                    hero_prompt = build_blog_hero_from_brief(
                        visual_brief=blog_visual_brief,
                        image_style=image_style,
                        is_img2img=bool(image_url),
                    )
                    logger.info(
                        "[Generate] Blog hero using inline visual_brief subject=%s",
                        blog_visual_brief.get("hero_subject", "")[:60],
                    )
                else:
                    # --- Standard path: Art Director LLM call ---
                    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
                    strategic_intel = getattr(shop_record, "strategic_intelligence", None) if shop_record else None
                    brand_soul = str(strategic_intel)[:300] if strategic_intel else ""
                    brand_name = body.get("brand_name", "")

                    product_name = body.get("product_name", "")
                    if not product_name:
                        product_name = (
                            body.get("collection_name")
                            or body.get("topic")
                            or body.get("subject_text")
                            or new_state.draft_title
                            or ""
                        )

                    short_desc = body.get("short_description", "")
                    if short_desc and product_name:
                        product_name = f"{product_name} — {short_desc}"

                    product_category = body.get("category", "General")

                    llm_svc = LLMService(db=db, shop_domain=shop)
                    brief = await generate_visual_brief(
                        product_name=product_name,
                        category=product_category,
                        brand_soul=brand_soul,
                        style=style_enum,
                        llm_service=llm_svc,
                    )

                    season = ""
                    season_props = ""
                    if style_enum == ImageStyle.SEASONAL:
                        season = get_current_season()
                        season_props = get_season_props(season)

                    if style_enum == ImageStyle.INFORMATIVE and not brand_name and shop_record:
                        brand_name = getattr(shop_record, "domain", "").split(".")[0].replace("-", " ").title()

                    hero_prompt = build_styled_prompt(
                        style=image_style,
                        brief=brief,
                        product_name=product_name,
                        brand_name=brand_name,
                        season=season,
                        season_props=season_props,
                        is_img2img=bool(image_url),
                    )

                # --- Generate hero image ---
                hero_gen = HeroImageGenerator()
                r2_svc = R2StorageService()

                if image_url:
                    hero_bytes = await hero_gen.generate_from_image(
                        image_url=image_url,
                        prompt=hero_prompt,
                    )
                else:
                    hero_bytes = await hero_gen.generate(prompt=hero_prompt)

                asset_tag = f"{template_id.replace('/', '-')}-{image_style}-{_uuid.uuid4().hex[:8]}"
                hero_key = R2StorageService.build_key(shop, "content-hero", asset_tag)
                hero_url = await r2_svc.upload_asset(hero_bytes, hero_key)

                logger.info(
                    "[Generate] Hero banner created template=%s shop=%s style=%s img2img=%s",
                    template_id, shop, image_style, bool(image_url),
                )

                # Deduct image credit
                try:
                    from src.ecommerce.db.transactions import record_feature_usage, log_usage_event

                    _ent = get_entitlements(plan_name)
                    _shop_rec = db.query(Shop).filter(Shop.domain == shop).first()
                    if _shop_rec:
                        if _ent.get("image_limit_type") == "lifetime":
                            cur = int(getattr(_shop_rec, "lifetime_image_credits_remaining", 0) or 0)
                            _shop_rec.lifetime_image_credits_remaining = max(0, cur - 1)
                        else:
                            cur = int(getattr(_shop_rec, "monthly_image_generations_used", 0) or 0)
                            _shop_rec.monthly_image_generations_used = cur + 1
                        db.add(_shop_rec)
                        db.commit()
                    record_feature_usage(db, shop, "image_generation", 1)
                    log_usage_event(
                        db, shop_domain=shop, plan_name=plan_name,
                        event_type="content_hero", feature="image_generation",
                        image_count=1,
                    )
                except Exception:
                    logger.debug("[Generate] image credit tracking failed", exc_info=True)
            except Exception as hero_err:
                logger.warning(
                    "[Generate] Hero generation failed (non-blocking) template=%s shop=%s err=%s",
                    template_id, shop, hero_err,
                )

        return {
            "status": "success",
            "template_id": template_id,
            "content": new_state.draft_content or new_state.draft_title or "",
            "title": new_state.draft_title,
            "description": new_state.draft_content,
            "hero_url": hero_url,
        }
    except Exception as e:
        logger.error(
            "[Generate] Template generation failed template=%s shop=%s err=%s",
            template_id,
            shop,
            e,
        )
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


# =============================================================================
# Shop Logo Endpoints
# =============================================================================

@router.post("/api/shop/logo")
async def upload_shop_logo(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Upload or update the shop logo.

    Accepts ``{ "logo_url": "https://..." }`` in the request body.
    Downloads the image and re-uploads it to R2 with a permanent key,
    then stores the R2 URL in ``shop.logo_url``.
    """
    import httpx
    from src.ecommerce.services.r2_storage_service import R2StorageService

    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    if not shop_record:
        raise HTTPException(status_code=404, detail="Shop not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    source_url = body.get("logo_url", "").strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="logo_url is required")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            logo_bytes = resp.content

        r2_svc = R2StorageService()
        logo_key = R2StorageService.build_key(shop, "brand-logo", "logo")
        r2_url = await r2_svc.upload_asset(logo_bytes, logo_key)

        shop_record.logo_url = r2_url
        db.commit()

        logger.info("[Logo] uploaded shop=%s url=%s", shop, r2_url[:80])

        return {"status": "success", "logo_url": r2_url}

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to download logo from provided URL: {e}",
        )
    except Exception as e:
        logger.error("[Logo] upload failed shop=%s err=%s", shop, e)
        raise HTTPException(status_code=500, detail=f"Logo upload failed: {e}")


@router.get("/api/shop/logo")
async def get_shop_logo(
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """Return the current shop logo URL."""
    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    if not shop_record:
        raise HTTPException(status_code=404, detail="Shop not found")

    return {"logo_url": getattr(shop_record, "logo_url", None)}


# =============================================================================
# Brand Intelligence Endpoints
# =============================================================================

@router.post("/api/admin/brand-intelligence/extract")
async def extract_brand_intelligence_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Extract strategic intelligence from existing brand context.
    
    Triggers the intelligence extraction pipeline on stored brand text.
    """
    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    if not shop_record:
        raise HTTPException(status_code=404, detail="Shop not found")
    
    if not shop_record.brand_context:
        raise HTTPException(status_code=404, detail="No brand context found. Please ingest brand context first.")
    
    try:
        # Get brand text
        brand_context = shop_record.brand_context
        if isinstance(brand_context, str):
            brand_context = json.loads(brand_context)
        
        brand_text = brand_context.get("en", {}).get("clean_text", "")
        if not brand_text:
            brand_text = brand_context.get("ja", {}).get("clean_text", "")
        
        if not brand_text:
            raise HTTPException(status_code=400, detail="No brand text found in brand context")
        
        # Extract intelligence
        llm_service = LLMService(db=db, shop_domain=shop)
        extractor = IntelligenceExtractorService(llm_service)
        
        existing_pillars = brand_context.get("en", {}).get("pillars", [])
        intel = await extractor.extract_strategic_audit(
            brand_text=brand_text,
            existing_pillars=existing_pillars if existing_pillars else None,
        )
        
        # Store
        shop_record.strategic_intelligence = intel.model_dump()
        shop_record.strategic_intelligence_updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return {
            "status": "success",
            "intelligence": intel.model_dump(),
            "updated_at": shop_record.strategic_intelligence_updated_at.isoformat(),
        }
    except Exception as e:
        logger.error(
            "[BrandIntel] Extraction failed shop=%s err=%s",
            shop,
            e,
        )
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Intelligence extraction failed: {str(e)}")


@router.get("/api/admin/brand-intelligence")
async def get_brand_intelligence_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Get stored strategic intelligence for a shop.
    """
    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    if not shop_record:
        raise HTTPException(status_code=404, detail="Shop not found")
    
    strategic_intel = getattr(shop_record, "strategic_intelligence", None)
    updated_at = getattr(shop_record, "strategic_intelligence_updated_at", None)
    
    return {
        "intelligence": strategic_intel,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


# =============================================================================
# Autonomous Publishing Endpoint (Pro tier)
# =============================================================================

@router.post("/api/publish")
async def publish_content(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Two-step publish: user generated content first, reviewed it, now publishes.
    Accepts either template_id (BaseAgent path) or action (legacy path).
    Pro tier only.
    """
    rid = _rid(request)
    body = await request.json()
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=False)
    validate_feature_access(auth_context, "autonomous")

    template_id = body.get("template_id")  # e.g. "marketing/email-launch"
    action = body.get("action")            # e.g. "price_scout"
    content = body.get("content")          # the generated content to publish
    product_id = body.get("product_id")
    context = body.get("context", {})

    logger.info(
        "[Publish] rid=%s shop=%s template_id=%s action=%s",
        rid, shop, template_id, action,
    )

    if template_id:
        return await _publish_via_agent(db, shop, template_id, content, product_id, body)
    elif action:
        return await _publish_via_action(db, shop, action, content, product_id, context)
    else:
        raise HTTPException(400, "Either template_id or action is required")


async def _publish_via_agent(db, shop, template_id, content, product_id, body):
    """Route to the agent's _maybe_publish() using PUBLISH_MAP."""
    from src.ecommerce.templates import get_template
    from src.ecommerce.state import MissionState
    from src.ecommerce.services.registry import ServiceRegistry

    template = get_template(template_id)
    if not template:
        raise HTTPException(404, f"Template '{template_id}' not found")

    # Build a lightweight MissionState with the content to publish
    state = MissionState(
        product_id=product_id or "",
        shop_id=shop,
        plan_tier="Pro",
        autonomous=True,
        draft_content=content,
        raw_input={"template_id": template_id, **body},
        db=db,
    )

    services = ServiceRegistry.create_default(db=db, shop_domain=shop)

    # Route to appropriate agent
    if template.agent_type.value == "rewriter":
        from src.ecommerce.agents.rewriter import RewriterAgent
        agent = RewriterAgent(shop_id=shop, services=services)
    elif template.agent_type.value == "marketing":
        from src.ecommerce.agents.marketing import MarketingAgent
        agent = MarketingAgent(shop_id=shop, services=services)
    else:
        raise HTTPException(400, f"Unknown agent type: {template.agent_type.value}")

    is_published, error = await agent._maybe_publish(state, template_id)
    return {"is_published": is_published, "error": error}


async def _publish_via_action(db, shop, action, content, product_id, context):
    """Route to PUBLISH_ACTION_MAP handler for legacy /api/agent actions."""
    from src.ecommerce.core.agent_actions import PUBLISH_ACTION_MAP

    handler = PUBLISH_ACTION_MAP.get(action)
    if not handler:
        raise HTTPException(400, f"No publish handler for action '{action}'")

    try:
        result = await handler(db=db, shop=shop, content=content, product_id=product_id, context=context)
        return {"is_published": True, "error": None, **(result or {})}
    except Exception as e:
        error_msg = str(e)
        logger.error("[Publish] action=%s shop=%s err=%s", action, shop, error_msg)
        return {"is_published": False, "error": error_msg}


# =============================================================================
# Meta Credentials Endpoints (Pro tier)
# =============================================================================

@router.post("/api/admin/meta-credentials")
async def save_meta_credentials(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Save Meta (Facebook/Instagram) API credentials for the shop.
    Pro tier only. Requires user consent before submission.
    """
    body = await request.json()
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=False)
    validate_feature_access(auth_context, "meta_integration")

    meta_access_token = body.get("meta_access_token")
    meta_page_id = body.get("meta_page_id")
    if not meta_access_token or not meta_page_id:
        raise HTTPException(400, "meta_access_token and meta_page_id are required")

    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    if not shop_record:
        raise HTTPException(404, "Shop not found")

    shop_record.meta_access_token = meta_access_token
    shop_record.meta_page_id = meta_page_id
    db.commit()

    logger.info("[MetaCreds] saved shop=%s page_id=%s", shop, meta_page_id)
    return {"status": "success", "has_meta_credentials": True}


@router.get("/api/admin/meta-credentials/status")
async def meta_credentials_status(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """Check Meta credentials status (does NOT expose the token)."""
    shop_record = db.query(Shop).filter(Shop.domain == shop).first()
    has_creds = bool(
        shop_record
        and getattr(shop_record, "meta_access_token", None)
        and getattr(shop_record, "meta_page_id", None)
    )
    return {
        "has_meta_credentials": has_creds,
        "meta_page_id": getattr(shop_record, "meta_page_id", None) if has_creds else None,
    }


# =============================================================================
# Retail Calendar
# =============================================================================

@router.get("/api/retail-calendar")
async def retail_calendar_endpoint(
    request: Request,
    shop: str = Depends(resolve_shop_domain),
):
    """Return the full US retail holiday calendar for the current year."""
    from src.ecommerce.agents.marketing.holidays import get_retail_calendar
    return {"calendar": get_retail_calendar()}


# =============================================================================
# Upload Product Image (for Marketing Studio)
# =============================================================================

_UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_UPLOAD_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

@router.post("/api/upload-product-image")
async def upload_product_image(
    request: Request,
    file: UploadFile = File(...),
    shop: str = Depends(resolve_shop_domain),
):
    """Upload a custom product image for ad generation, stored in R2."""
    if file.content_type not in _UPLOAD_ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: {', '.join(sorted(_UPLOAD_ALLOWED_TYPES))}",
        )

    data = await file.read()
    if len(data) > _UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    from src.ecommerce.services.r2_storage_service import R2StorageService
    import uuid

    r2_svc = R2StorageService()
    ext = (file.filename or "upload.png").rsplit(".", 1)[-1] or "png"
    key = R2StorageService.build_key(shop, f"custom-{uuid.uuid4().hex[:12]}", f"upload.{ext}")
    url = await r2_svc.upload_asset(data, key, content_type=file.content_type or "image/png")

    return {"url": url, "key": key}


# ---------------------------------------------------------
# Merchant Concern Submission
# ---------------------------------------------------------
from pydantic import BaseModel as _BaseModel

class _SubmitConcernReq(_BaseModel):
    subject: str
    message: str
    email: str = ""


@router.post("/api/admin/submit-concern")
async def submit_concern(body: _SubmitConcernReq, shop: str = Depends(resolve_shop_domain), db: Session = Depends(get_db)):
    from src.ecommerce.db.models import ConcernLog
    concern = ConcernLog(
        shop_domain=shop,
        email=body.email,
        subject=body.subject,
        message=body.message,
        status="open",
    )
    db.add(concern)
    db.commit()
    db.refresh(concern)
    return {"message": "Concern submitted", "concern_id": concern.id}

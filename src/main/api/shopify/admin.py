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
from src.main.services.brand_ingest_service import (
    ingest_brand_context,
    ingest_brand_context_with_intelligence,
    scrape_urls,
    extract_file_text,
)
from src.main.services.intelligence_extractor import IntelligenceExtractorService
from src.main.services.llm_service import LLMService
from src.main.services.rag_service import RAGService
from datetime import datetime, timezone
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


# =============================================================================
# Template Endpoints
# =============================================================================

@router.get("/api/templates")
async def list_templates_endpoint(
    request: Request,
    category: str = None,
    agent_type: str = None,
    tier: str = None,
):
    """
    List available content templates.
    
    Args:
        category: Filter by category (product/marketing)
        agent_type: Filter by agent type (rewriter/marketing)
        tier: Filter by minimum tier required (Free/Basic/Standard/Pro)
    
    Returns:
        List of template objects
    """
    from src.main.agents.templates import (
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
        tier=tier,
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
                "tier_required": t.tier_required,
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
        template_id: Template ID (e.g., "product/title", "marketing/email-launch")
        request: Request body with template inputs
    
    Returns:
        Generated content
    """
    from src.main.agents.templates import get_template
    from src.main.agents.state import MissionState
    from src.main.services.registry import ServiceRegistry
    
    # Get template
    template = get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    
    # Parse request body
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    # Get plan tier for routing
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=False)
    plan_name = auth_context.get("effective_plan_name") or "Free"
    
    # Check tier access
    tier_order = ["Free", "Basic", "Standard", "Pro"]
    template_tier_index = tier_order.index(template.tier_required) if template.tier_required in tier_order else 0
    plan_tier_index = tier_order.index(plan_name) if plan_name in tier_order else 0
    if plan_tier_index < template_tier_index:
        raise HTTPException(
            status_code=403,
            detail=f"Template '{template_id}' requires {template.tier_required} plan. Current plan: {plan_name}",
        )
    
    # Build mission state
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
        from src.main.agents.rewriter import RewriterAgent
        agent = RewriterAgent(shop_id=shop, services=services)
    elif template.agent_type.value == "marketing":
        from src.main.agents.marketing import MarketingAgent
        agent = MarketingAgent(shop_id=shop, services=services)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {template.agent_type.value}")
    
    # Execute agent
    try:
        new_state = await agent.run(state)
        
        return {
            "status": "success",
            "template_id": template_id,
            "content": new_state.draft_content or new_state.draft_title or "",
            "title": new_state.draft_title,
            "description": new_state.draft_content,
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

"""
Shopify Proxy Routes

Handles Theme App Proxy and Admin Extension endpoints for product copy generation.
"""

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.ecommerce.api.models import RewriteRequest, BulkRewriteRequest, AgentRequest
from src.shared.db.database import get_db
from src.ecommerce.db.transactions import record_successful_rewrite, record_feature_usage, log_usage_event
from src.ecommerce.api.validation import (
    validate_rewrite_request,
    validate_shop_and_quota,
    validate_agent_action_access,
    validate_feature_access,
)
from src.shared.security.security import verify_shopify_proxy_request
from src.ecommerce.core.generation import process_generation_request, process_bulk_generation_request
from src.ecommerce.core.shop import fetch_shop_locales
from src.ecommerce.core.agent_actions import run_agent_action
from src.shared.logging.logger import get_logger

from .shared import resolve_shop_domain, _rid

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# App Proxy Endpoints (Theme Frontend)
# =============================================================================

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
    if isinstance(resp, dict) and resp.get("status") == "success":
        try:
            record_successful_rewrite(db, shop_domain, amount=1)
            record_feature_usage(db, shop_domain, "rewriter", 1)
            plan_name = getattr(auth_context.get("plan"), "name", "Free")
            log_usage_event(
                db, shop_domain=shop_domain, plan_name=plan_name,
                event_type="product_rewrite", feature="rewriter",
                product_count=1, product_id=getattr(rewrite_request, "product_id", None),
                action="generate-copy",
            )
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
            record_feature_usage(db, shop_domain, "rewriter", 1)
            plan_name = getattr(auth_context.get("plan"), "name", "Free")
            log_usage_event(
                db, shop_domain=shop_domain, plan_name=plan_name,
                event_type="bulk_rewrite", feature="rewriter",
                product_count=1, product_id=getattr(bulk_request, "product_id", None),
                action="generate-bulk",
            )
        except Exception as e:
            logger.warning(f"Rewrite increment skipped for shop={shop_domain}: {e}")
    return resp


# =============================================================================
# Admin Extension Endpoints (Shopify Admin UI)
# =============================================================================

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
            record_feature_usage(db, shop, "rewriter", 1)
            plan_name = getattr(auth_context.get("plan"), "name", "Free")
            log_usage_event(
                db, shop_domain=shop, plan_name=plan_name,
                event_type="bulk_rewrite", feature="rewriter",
                product_count=1, product_id=getattr(bulk_request, "product_id", None),
                action="admin-bulk-generate",
            )
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


# =============================================================================
# Agent Endpoint (Action-based, backend-agnostic)
# =============================================================================

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

    auth_context = validate_shop_and_quota(db, shop, enforce_limit=True)
    validate_agent_action_access(auth_context, agent_req.action)

    logger.info("[Agent] start rid=%s shop=%s action=%s", rid, shop, agent_req.action)

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
        db=db,
        shop_domain=shop,
    )

    try:
        from src.ecommerce.api.validation import _ACTION_TO_FEATURE
        _feat = _ACTION_TO_FEATURE.get(agent_req.action, "rewriter")
        record_feature_usage(db, shop, _feat, 1)
        plan_name = getattr(auth_context.get("plan"), "name", "Free")
        log_usage_event(
            db, shop_domain=shop, plan_name=plan_name,
            event_type=agent_req.action, feature=_feat,
            product_count=1, action=agent_req.action,
        )
    except Exception:
        pass

    logger.info("[Agent] done rid=%s shop=%s action=%s", rid, shop, agent_req.action)
    return {"status": "success", "data": {"text": result.get("text", ""), "metadata": result.get("metadata", {})}}


# =============================================================================
# API Agent Endpoint (Alias for /apps/cross-border/agent)
# =============================================================================

@router.options("/api/agent")
async def api_agent_preflight():
    """CORS preflight for /api/agent endpoint."""
    return Response(status_code=204)


@router.post("/api/agent")
async def api_agent(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Action-based endpoint for ad-hoc agent calls from the frontend.
    This is an alias for /apps/cross-border/agent with simpler path.
    
    Used by SEO, Marketing, and Pricing pages for synchronous agent actions.
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

    auth_context = validate_shop_and_quota(db, shop, enforce_limit=True)
    validate_agent_action_access(auth_context, agent_req.action)

    logger.info("[Agent] start rid=%s shop=%s action=%s", rid, shop, agent_req.action)

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
        db=db,
        shop_domain=shop,
    )

    try:
        from src.ecommerce.api.validation import _ACTION_TO_FEATURE
        _feat = _ACTION_TO_FEATURE.get(agent_req.action, "rewriter")
        record_feature_usage(db, shop, _feat, 1)
        plan_name = getattr(auth_context.get("plan"), "name", "Free")
        log_usage_event(
            db, shop_domain=shop, plan_name=plan_name,
            event_type=agent_req.action, feature=_feat,
            product_count=1, action=agent_req.action,
        )
    except Exception:
        pass

    logger.info("[Agent] done rid=%s shop=%s action=%s", rid, shop, agent_req.action)
    return {"status": "success", "data": {"text": result.get("text", ""), "metadata": result.get("metadata", {})}}


# =============================================================================
# Deprecated Direct Endpoint
# =============================================================================

@router.post("/api/generate-copy")
async def generate_copy(
    request: RewriteRequest,
    db: Session = Depends(get_db)
):
    raise HTTPException(status_code=410, detail="This endpoint is deprecated. Please use the Shopify App Proxy.")


# =============================================================================
# Shop Locales Endpoint
# =============================================================================

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

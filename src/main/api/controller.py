from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query, Header
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import secrets
import os
import jwt

from .models import RewriteRequest, OnboardingRequest, BulkRewriteRequest, AgentRequest
from src.main.db.db_models import User
from src.main.db.database import get_db
from src.main.db.db_transactions import (
    get_plan_by_name,
    store_shop_access_token,
    record_successful_rewrite,
)
from src.main.db.db_transactions import get_user_by_username
from src.main.db.db_models import Shop, User, Plan
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
from src.main.config.configs import SHOPIFY_UI_URL
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
        rewrite_request = RewriteRequest(**body)
    except Exception:
        logger.info("[Copy] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")

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
        bulk_request = BulkRewriteRequest(**body)
    except Exception:
        logger.info("[Bulk] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")

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
        bulk_request = BulkRewriteRequest(**body)
    except Exception:
        logger.info("[AdminBulk] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")

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
        agent_req = AgentRequest(**body)
    except Exception:
        logger.info("[Agent] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")

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
        "plan_name": plan.name,
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
    }


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
        
        if app_subscription:
            # Standard Shopify webhook
            shop_domain = request.headers.get("X-Shopify-Shop-Domain")
            plan_name = app_subscription.get('name')
            status = app_subscription.get('status')
            
            if status != "ACTIVE":
                logger.info(f"Subscription update for {shop_domain} with status {status}. Skipping onboarding.")
                return Response(status_code=200)
        else:
            # Fallback for manual/custom triggers
            shop_domain = payload.get('myshopify_domain')
            plan_name = payload.get('billing_plan') 
        
        if not shop_domain or not plan_name:
            logger.warning("Webhook payload missing shop domain or plan name")
            return Response(status_code=200)

        plan = get_plan_by_name(db, plan_name)
        if not plan:
            logger.warning(f"Webhook received for unknown plan: {plan_name}")
            return Response(status_code=200)

        # ACTION: Explicitly update the User's plan in DB to ensure immediate effect
        # Wrap in try/except to avoid failing when test DB tables are absent.
        try:
            user = get_user_by_username(db, shop_domain)
            if user:
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
                    shop_rec.is_active = False
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

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query, Header
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import secrets
import os
import jwt

from .models import RewriteRequest, OnboardingRequest, BulkRewriteRequest, AgentRequest
from src.main.db.db_models import User
from src.main.db.database import get_db
from src.main.db.db_transactions import get_plan_by_name, store_shop_access_token
from src.main.db.db_transactions import get_user_by_username
from src.main.db.db_models import Shop, User
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
from src.main.logging.logger import get_logger

# Import core business logic
from src.main.core.generation import process_generation_request, process_bulk_generation_request
from src.main.core.shop import fetch_shop_locales
from src.main.core.agent_actions import run_agent_action

logger = get_logger(__name__)

router = APIRouter()

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

# ==============================================================================
#  0. OAUTH ENTRY POINT (Install App)
# ==============================================================================
@router.get("/")
async def install_app(shop: str = Query(..., description="Shopify Shop Domain")):
    """
    Redirects the user to Shopify's OAuth authorization page.
    """
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")
    
    logger.info(f"[Install] Received install request for shop={shop}")

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
    try:
        body = await request.json()
        rewrite_request = RewriteRequest(**body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    validate_rewrite_request(rewrite_request.model_dump())

    shop_domain = request.query_params.get("shop")
    if not shop_domain:
         raise HTTPException(status_code=400, detail="Missing shop parameter")

    auth_context = validate_shop_and_quota(db, shop_domain)
    
    # Delegate business logic to Core layer
    return await process_generation_request(
        db=db,
        request=rewrite_request,
        user=auth_context["user"],
        plan=auth_context["plan"],
        user_id=auth_context["user_id"],
        billing_cycle_start=auth_context["billing_cycle_start"]
    )


@router.post("/api/proxy/generate-bulk")
async def proxy_generate_bulk(
    request: Request,
    db: Session = Depends(get_db),
    shop_domain: str = Depends(resolve_shop_domain),
):
    try:
        body = await request.json()
        bulk_request = BulkRewriteRequest(**body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    auth_context = validate_shop_and_quota(db, shop_domain)
    
    return await process_bulk_generation_request(
        db=db,
        request=bulk_request,
        user=auth_context["user"],
        plan=auth_context["plan"],
        user_id=auth_context["user_id"],
        billing_cycle_start=auth_context["billing_cycle_start"]
    )


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
    try:
        body = await request.json()
        bulk_request = BulkRewriteRequest(**body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    auth_context = validate_shop_and_quota(db, shop)

    return await process_bulk_generation_request(
        db=db,
        request=bulk_request,
        user=auth_context["user"],
        plan=auth_context["plan"],
        user_id=auth_context["user_id"],
        billing_cycle_start=auth_context["billing_cycle_start"],
    )


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
    try:
        body = await request.json()
        agent_req = AgentRequest(**body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    auth_context = validate_shop_and_quota(db, shop)

    result = run_agent_action(
        action=agent_req.action,
        context=agent_req.context or {},
        product_data=agent_req.product_data or {},
    )

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
    shop: str = Depends(verify_shopify_session)
):
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

    auth_context = validate_shop_and_quota(db, shop_domain)
    
    user = auth_context["user"]
    plan = auth_context["plan"]
    usage = auth_context["current_usage"]
    
    return {
        "current_usage": usage,
        "monthly_token_quota": plan.monthly_token_quota,
        "plan_name": plan.name,
        "is_pro": plan.name == "Pro" or plan.name == "Growth" # Flag for the widget
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

    logger.info(f"[Sync Token] Storing token for shop={shop}, type={token_type}, force={force}")
    store_shop_access_token(db, shop, access_token, token_type=token_type, force=force)
    return Response(status_code=204)

@router.post("/webhooks/subscription-activated")
async def handle_subscription_activated(
    request: Request,
    db: Session = Depends(get_db)
):
    await verify_webhook_signature(request)
    
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

        logger.info(f"🗑️ app/uninstalled received for {shop_domain}")

        if shop_domain:
            # Delete Shop and User records if they exist (best-effort).
            try:
                shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
                if shop_rec:
                    db.delete(shop_rec)
                    db.commit()
            except Exception as e:
                logger.warning(f"Unable to delete shop record for {shop_domain}: {e}")
                db.rollback()

            try:
                user = get_user_by_username(db, shop_domain)
                if user:
                    db.delete(user)
                    db.commit()
            except Exception as e:
                logger.warning(f"Unable to delete user record for {shop_domain}: {e}")
                db.rollback()

    except Exception as e:
        logger.error(f"Error handling app/uninstalled webhook: {e}")

    # Always return 200 quickly to avoid retries/timeouts
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
            logger.info(f"Auth callback params: host={host}, state={params.get('state')}, timestamp={params.get('timestamp')}")
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
    params = dict(request.query_params)
    logger.info(f"PROXY REQ locales: {params}")
    return await fetch_shop_locales(db, shop)

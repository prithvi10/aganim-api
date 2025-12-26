from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import secrets
import os

from .models import RewriteRequest, OnboardingRequest, BulkRewriteRequest
from src.main.db.db_models import User
from src.main.db.database import get_db
from src.main.db.db_transactions import get_plan_by_name, store_shop_access_token
from src.main.security.security import (
    verify_shopify_session, 
    verify_webhook_signature, 
    verify_shopify_redirect,
    SHOPIFY_API_KEY,
    SHOPIFY_API_SECRET
)
from src.main.api.validation import validate_rewrite_request, validate_shop_and_quota 
from src.main.service.onboarding import onboard_user
from src.main.logging.logger import get_logger

# Import core business logic
from src.main.core.generation import process_generation_request, process_bulk_generation_request
from src.main.core.shop import fetch_shop_locales

logger = get_logger(__name__)

router = APIRouter()

SCOPES = "read_products,write_products,read_locales,read_translations,write_translations,read_files"
SHOPIFY_REDIRECT_URI = "https://shopify-translator-api.onrender.com/api/auth/callback"

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
    db: Session = Depends(get_db)
):
    try:
        body = await request.json()
        bulk_request = BulkRewriteRequest(**body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    shop_domain = request.query_params.get("shop")
    if not shop_domain:
         raise HTTPException(status_code=400, detail="Missing shop parameter")

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

@router.post("/webhooks/subscription-activated")
async def handle_subscription_activated(
    request: Request,
    db: Session = Depends(get_db)
):
    await verify_webhook_signature(request)
    
    try:
        payload = await request.json()
        shop_domain = payload.get('myshopify_domain')
        plan_name = payload.get('billing_plan') 
        
        if not shop_domain or not plan_name:
            logger.warning("Webhook payload missing 'myshopify_domain' or 'billing_plan'")
            return Response(status_code=200)

        plan = get_plan_by_name(db, plan_name)
        if not plan:
            logger.warning(f"Webhook received for unknown plan: {plan_name}")
            return Response(status_code=200)

        onboarding_req = OnboardingRequest(
            username=shop_domain,
            plan_id=plan.id,
            email=payload.get('email')
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
            store_shop_access_token(db, shop, access_token)
            
            return {
                "status": "success", 
                "message": "App installed successfully", 
                "shop": shop,
                "host": host
            }

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
async def get_shop_locales(request: Request, db: Session = Depends(get_db)):
    """
    Fetches the enabled locales for the shop.
    Delegates to Core layer.
    """
    shop_domain = request.query_params.get("shop")
    return await fetch_shop_locales(db, shop_domain)

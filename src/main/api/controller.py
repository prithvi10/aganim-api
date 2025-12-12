from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
from .models import RewriteRequest, OnboardingRequest
from src.main.service.services import OpenAIService
from src.main.security.security import (
    get_api_key_hash, 
    verify_shopify_session, 
    verify_webhook_signature, 
    verify_shopify_redirect,
    SHOPIFY_API_KEY,
    SHOPIFY_API_SECRET
)
from src.main.security.ratelimiter import InMemoryRateLimiter
from src.main.config.configs import LOCAL_RATE_LIMIT_CONFIG
from src.main.logging.logger import get_logger
from src.main.db.database import get_db
from src.main.db.db_transactions import update_token_usage, get_plan_by_name
from src.main.service.streaming_utils import create_streaming_response
from src.main.api.validation import validate_api_key_and_quota, validate_rewrite_request
from src.main.service.onboarding import onboard_user
import httpx

logger = get_logger(__name__)

router = APIRouter()
#Initialize the Limiter GLOBALLY
limiter = InMemoryRateLimiter(LOCAL_RATE_LIMIT_CONFIG)
openai_service = OpenAIService()

# ------------------------------------------------------------------
# 1. PUBLIC/CLIENT ENDPOINT (Uses API Key for Billing/Quota)
# ------------------------------------------------------------------
@router.post("/api/generate-copy")
async def generate_copy(
    request: RewriteRequest,
    key_hash: str = Depends(get_api_key_hash),
    db: Session = Depends(get_db)
):
    # 0. Validate Request Body
    validate_rewrite_request(request.model_dump())

    # 1. Verify API Key and Quota (Read Operation)
    # This returns a context dict with user, plan, etc.
    auth_context = validate_api_key_and_quota(db, key_hash)
    
    user = auth_context["user"]
    shop = user.username # Assuming username is shop domain
    api_key_id = auth_context["api_key_id"]
    billing_cycle_start = auth_context["billing_cycle_start"]
    plan = auth_context["plan"]

    logger.info(f"✅ Verified request from: {shop}")

    # 2. Check Rate Limit
    if not limiter.is_allowed(shop):
        logger.warning(f"Rate limit exceeded for shop: {shop}")
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")
    
    logger.info(f"✅ Rate limit check passed for shop: {shop}")

    # 3. Check for Streaming Capability (Optional Gate)
    if request.stream and not plan.can_stream_responses:
        # If user requests stream but plan doesn't support it
        logger.warning(f"Shop {shop} requested streaming but plan {plan.name} does not support it.")
        # We can either fail or fallback to non-streaming. Let's fail for clarity.
        raise HTTPException(status_code=403, detail="Streaming not supported on your current plan.")
    
    try:
        # 4. Handle Streaming Request
        if request.stream:
             logger.info(f"🌊 Initiating Streaming Response for: {shop}")
             return create_streaming_response(
                openai_service=openai_service,
                product_name=request.product_name,
                category=request.category,
                japanese_description=request.japanese_description,
                db=db,
                api_key_id=api_key_id,
                billing_cycle_start=billing_cycle_start
             )

        # 5. Handle Standard Request (Legacy/Non-Stream)
        openai_response = openai_service.generate_copy(
            product_name=request.product_name,
            category=request.category,
            japanese_description=request.japanese_description
        )
        
        # 3. Update Token Usage (CRITICAL FIX)
        # --- A. Safely extract usage ---
        total_tokens_used = 0
        
        # This structure works for non-streaming calls:
        if hasattr(openai_response, 'usage') and openai_response.usage:
            total_tokens_used = openai_response.usage.total_tokens
        
        # --- B. Execute Atomic Update ---
        # The database handles the atomic increment based on the final, known token count
        if total_tokens_used > 0:
            update_token_usage(db, api_key_id, total_tokens_used, billing_cycle_start)

        logger.info(f"✅ Translated description. Tokens used: {total_tokens_used}")
        return {
            "status": "success",
            "english_copy": openai_response.choices[0].message.content # Return content from the object
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error calling OpenAI API - ACTUAL ERROR: {type(e).__name__} - {e}")
        if e.__cause__:
            logger.error(f"❌ Error calling OpenAI API - ROOT CAUSE: {e.__cause__}")
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------------------------------------------
# 2. ADMIN/SETUP ENDPOINT (Uses Shopify JWT)
# ------------------------------------------------------------------
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
    """
    Shopify Webhook for subscription activation.
    Triggers the onboarding process for the merchant.
    """
    # 1. Shopify Webhook Verification
    await verify_webhook_signature(request)
    
    # 2. Extract Merchant and Subscription data
    try:
        payload = await request.json()
        shop_domain = payload.get('myshopify_domain')
        # Note: 'billing_plan' might be nested or named differently depending on the specific webhook topic
        # For 'app_subscriptions/update', it's often in the 'name' field of the plan object
        # We'll stick to the user's provided structure for now, but fail gracefully.
        plan_name = payload.get('billing_plan') 
        
        if not shop_domain or not plan_name:
            logger.warning("Webhook payload missing 'myshopify_domain' or 'billing_plan'")
            return Response(status_code=200) # Return 200 to acknowledge receipt

        # 3. Resolve Plan
        plan = get_plan_by_name(db, plan_name)
        if not plan:
            logger.warning(f"Webhook received for unknown plan: {plan_name}")
            return Response(status_code=200)

        # 4. Call Core Onboarding Service
        onboarding_req = OnboardingRequest(
            username=shop_domain,
            plan_id=plan.id,
            email=payload.get('email') # Optional: try to get email if available
        )
        
        # We catch exceptions because we want to acknowledge the webhook with 200 OK 
        # even if our logic fails (e.g. duplicate user), to stop Shopify from retrying.
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
        # Still return 200 to prevent retry storms if payload is malformed
        return Response(status_code=200)

    # 5. Success response
    return Response(status_code=200)

@router.get("/api/auth/callback")
async def auth_callback(request: Request):
    """
    Shopify OAuth Redirect Handler.
    Validates HMAC and exchanges code for access token.
    This URL must be whitelisted in Shopify Partner Dashboard.
    """
    params = dict(request.query_params)
    
    # 1. Verify HMAC
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

    # 2. Exchange code for access token
    # POST https://{shop}/admin/oauth/access_token
    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, json=payload)
            response.raise_for_status()
            token_data = response.json()
            
            access_token = token_data.get("access_token")
            # Scope can also be checked here if needed
            
            logger.info(f"Successfully exchanged token for shop: {shop}")
            
            # 3. Session Creation / Redirect
            # In a full app, you would:
            # - Store the access_token in the DB (encrypted) associated with the shop
            # - Create a user session (cookie/JWT)
            # - Redirect the user to the embedded app UI (https://admin.shopify.com/store/...)
            
            # For now, we return success to satisfy the Safety Whitelist requirement check
            # and acknowledge the flow completion.
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

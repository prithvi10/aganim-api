from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from .models import RewriteRequest
from src.main.service.services import OpenAIService
from src.main.security.security import get_api_key_hash, verify_shopify_session
from src.main.security.ratelimiter import InMemoryRateLimiter
from src.main.config.configs import LOCAL_RATE_LIMIT_CONFIG
from src.main.logging.logger import get_logger
from src.main.db.database import get_db
from src.main.db.db_transactions import verify_api_key_and_quota, update_token_usage
from src.main.service.streaming_utils import create_streaming_response

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
    # 1. Verify API Key and Quota (Read Operation)
    # This returns a context dict with user, plan, etc.
    auth_context = verify_api_key_and_quota(db, key_hash)
    
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

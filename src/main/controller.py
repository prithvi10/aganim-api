from fastapi import APIRouter, HTTPException, Depends
from .models import RewriteRequest
from .services import OpenAIService
from .security import verify_shopify_session
from .ratelimiter import InMemoryRateLimiter
from .configs import LOCAL_RATE_LIMIT_CONFIG

router = APIRouter()
#Initialize the Limiter GLOBALLY
limiter = InMemoryRateLimiter(LOCAL_RATE_LIMIT_CONFIG)
openai_service = OpenAIService()

@router.post("/api/generate-copy")
async def generate_copy(
    request: RewriteRequest,
    shop: str = Depends(verify_shopify_session)
):
    print(f"✅ Verified request from: {shop}")
    # Check Rate Limit
    # We pass the 'shop' ID we just got from the security check
    if not limiter.is_allowed(shop):
        # Return 429 Error
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")
    print(f"✅ Rate limit check passed for shop: {shop}")
    try:
        english_copy = openai_service.generate_copy(
            product_name=request.product_name,
            category=request.category,
            japanese_description=request.japanese_description
        )
        # TODO : Remove before going to PROD
        # english_copy = "Test Copy"

        return {
            "status": "success",
            "english_copy": english_copy
        }

    except Exception as e:
        print(f"DEBUG - ACTUAL ERROR: {type(e).__name__} - {e}")
        print(f"DEBUG - ROOT CAUSE: {e.__cause__}")
        #print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


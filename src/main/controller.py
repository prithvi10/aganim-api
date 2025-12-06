from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from .models import RewriteRequest
from .services import OpenAIService
from .security import verify_shopify_session
from .ratelimiter import InMemoryRateLimiter
from .configs import LOCAL_RATE_LIMIT_CONFIG
from .logger import get_logger
from .database import get_db
from .db_models import User, Usage

logger = get_logger(__name__)

router = APIRouter()
#Initialize the Limiter GLOBALLY
limiter = InMemoryRateLimiter(LOCAL_RATE_LIMIT_CONFIG)
openai_service = OpenAIService()

def get_or_create_user(db: Session, shop_domain: str):
    user = db.query(User).filter(User.username == shop_domain).first()
    if not user:
        user = User(username=shop_domain)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def check_quota(db: Session, user: User):
    current_month = datetime.now().strftime("%Y-%m")
    usage = db.query(Usage).filter(Usage.user_id == user.id, Usage.month == current_month).first()
    
    if not usage:
        usage = Usage(user_id=user.id, month=current_month, usage_count=0)
        db.add(usage)
        db.commit()
        db.refresh(usage)
    
    if usage.usage_count >= user.monthly_quota:
         raise HTTPException(status_code=403, detail="Monthly quota exceeded.")
    
    return usage

@router.post("/api/generate-copy")
async def generate_copy(
    request: RewriteRequest,
    shop: str = Depends(verify_shopify_session),
    db: Session = Depends(get_db)
):
    logger.info(f"✅ Verified request from: {shop}")

    # 1. Check Database Quota
    user = get_or_create_user(db, shop)
    usage_record = check_quota(db, user)

    # 2. Check Rate Limit
    # We pass the 'shop' ID we just got from the security check
    if not limiter.is_allowed(shop):
        # Return 429 Error
        logger.warning(f"Rate limit exceeded for shop: {shop}")
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")
    
    logger.info(f"✅ Rate limit check passed for shop: {shop}")
    try:
        english_copy = openai_service.generate_copy(
            product_name=request.product_name,
            category=request.category,
            japanese_description=request.japanese_description
        )
        
        # Increment Usage
        usage_record.usage_count += 1
        db.commit()

        logger.info(f"✅ English copy generated for product: {request.product_name}")
        return {
            "status": "success",
            "english_copy": english_copy
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error calling OpenAI API - ACTUAL ERROR: {type(e).__name__} - {e}")
        if e.__cause__:
            logger.error(f"❌ Error calling OpenAI API - ROOT CAUSE: {e.__cause__}")
        raise HTTPException(status_code=500, detail=str(e))


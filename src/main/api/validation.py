from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.main.db.db_transactions import get_shop_quota_context
from src.main.logging.logger import get_logger

logger = get_logger(__name__)

def validate_api_key_and_quota(db: Session, key_hash: str):
    """
    DEPRECATED: Validates the API key and ensures the user has sufficient quota.
    This function is kept for backward compatibility if we decide to re-implement direct API access
    using a different auth mechanism in the future.
    For now, it will raise an error as API Keys are no longer supported.
    """
    raise HTTPException(status_code=410, detail="API Key authentication is deprecated. Please use the Shopify App Proxy.")

def validate_shop_and_quota(db: Session, shop_domain: str):
    """
    Validates the Shop (User) and ensures they have sufficient quota.
    Uses the User ID for metering.
    Raises HTTPException if validation fails.
    """
    if not shop_domain:
        raise HTTPException(status_code=401, detail="Missing Shop Domain")

    # 1. Fetch Context from DB
    context = get_shop_quota_context(db, shop_domain)

    if not context:
        logger.warning(f"⛔ Authorization Failed: Invalid or Inactive Shop {shop_domain}")
        raise HTTPException(status_code=401, detail="Invalid Shop or User not found")

    user = context["user"]
    plan = context["plan"]
    current_usage = context["current_usage"]

    # 2. Check Quota Logic
    if current_usage >= plan.monthly_token_quota:
        logger.warning(f"⛔ Quota Exceeded: User {user.username} (Usage: {current_usage} / Limit: {plan.monthly_token_quota})")
        raise HTTPException(
            status_code=429, 
            detail=f"Monthly token quota exceeded. ({current_usage}/{plan.monthly_token_quota})"
        )

    return context

def validate_rewrite_request(request_body: dict):
    """
    Additional validation for the request body beyond Pydantic types.
    """
    if not request_body.get("japanese_description") or not request_body["japanese_description"].strip():
        raise HTTPException(status_code=422, detail="Japanese description cannot be empty or whitespace only.")
    
    if len(request_body["japanese_description"]) > 5000:
        raise HTTPException(status_code=422, detail="Description too long (max 5000 characters).")



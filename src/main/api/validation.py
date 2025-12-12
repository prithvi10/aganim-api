from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.main.db.db_transactions import get_user_quota_context, get_shop_quota_context
from src.main.logging.logger import get_logger

logger = get_logger(__name__)

def validate_api_key_and_quota(db: Session, key_hash: str):
    """
    Validates the API key and ensures the user has sufficient quota.
    Raises HTTPException if validation fails.
    """
    if not key_hash:
        raise HTTPException(status_code=401, detail="Missing API Key")

    # 1. Fetch Context from DB (Pure DB operation)
    context = get_user_quota_context(db, key_hash)

    if not context:
        logger.warning(f"⛔ Authorization Failed: Invalid API Key Hash {key_hash}")
        raise HTTPException(status_code=401, detail="Invalid API Key")

    user = context["user"]
    plan = context["plan"]
    current_usage = context["current_usage"]

    if not context["is_active"]:
        logger.warning(f"⛔ Authorization Failed: Inactive API Key for user {user.username}")
        raise HTTPException(status_code=401, detail="Inactive API Key")

    # 2. Check Quota Logic
    if current_usage >= plan.monthly_token_quota:
        logger.warning(f"⛔ Quota Exceeded: User {user.username} (Usage: {current_usage} / Limit: {plan.monthly_token_quota})")
        raise HTTPException(
            status_code=429, 
            detail=f"Monthly token quota exceeded. ({current_usage}/{plan.monthly_token_quota})"
        )

    return context

def validate_shop_and_quota(db: Session, shop_domain: str):
    """
    Validates the Shop (User) and ensures they have sufficient quota.
    Uses an active API Key linked to the shop for metering.
    Raises HTTPException if validation fails.
    """
    if not shop_domain:
        raise HTTPException(status_code=401, detail="Missing Shop Domain")

    # 1. Fetch Context from DB
    context = get_shop_quota_context(db, shop_domain)

    if not context:
        logger.warning(f"⛔ Authorization Failed: Invalid or Inactive Shop {shop_domain}")
        raise HTTPException(status_code=401, detail="Invalid Shop or No Active API Key")

    user = context["user"]
    plan = context["plan"]
    current_usage = context["current_usage"]

    if not context["is_active"]:
        logger.warning(f"⛔ Authorization Failed: Inactive API Key for user {user.username}")
        raise HTTPException(status_code=401, detail="Inactive API Key")

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


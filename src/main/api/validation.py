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

def validate_shop_and_quota(db: Session, shop_domain: str, *, enforce_limit: bool = True):
    """
    Validates the Shop (User) and ensures they have sufficient rewrite quota (unless enforce_limit=False).
    Uses the Shop record for metering and self-healing monthly resets.
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
    shop = context["shop"]
    rewrites_used = context["rewrites_used"]
    rewrite_limit = context["rewrite_limit"]
    billing_cycle_type = str(context.get("billing_cycle_type") or getattr(plan, "billing_cycle_type", "") or "").strip().lower()
    if not billing_cycle_type:
        billing_cycle_type = "lifetime" if str(getattr(plan, "name", "") or "") == "Free" else "recurring"

    # 2. Check Quota Logic
    if enforce_limit and rewrite_limit is not None and int(rewrite_limit) != -1:
        if billing_cycle_type == "lifetime":
            remaining = int(context.get("lifetime_rewrites_remaining") or 0)
            if remaining <= 0:
                logger.warning(
                    "[FreePlan] limit_reached shop=%s used=%s limit=%s",
                    user.username,
                    rewrites_used,
                    rewrite_limit,
                )
                raise HTTPException(
                    status_code=403,
                    detail="You've used your 10 free lifetime credits. Upgrade to Basic for 50 rewrites every month!",
                )
        else:
            if int(rewrites_used) >= int(rewrite_limit):
                reset_on = shop.next_reset_date.isoformat() if getattr(shop, "next_reset_date", None) else "unknown"
                logger.warning(
                    f"⛔ Monthly Limit Reached: shop={user.username} (used={rewrites_used} / limit={rewrite_limit}) reset_on={reset_on}"
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Monthly limit reached. Your limit resets on {reset_on}.",
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



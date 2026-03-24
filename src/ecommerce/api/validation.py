from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.ecommerce.db.transactions import get_shop_quota_context
from src.ecommerce.plans.entitlements import PLAN_ENTITLEMENTS, get_entitlements, get_required_tier
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

# Maps agent action names to the feature entitlement key they require
_ACTION_TO_FEATURE: dict[str, str] = {
    "seo_optimize": "seo",
    "price_scout": "price_scout",
    "social_hook_architect": "marketing",
    "seasonal_campaign_agent": "marketing",
    "seasonal_campaign_caption": "marketing",
    "value_discovery": "rewriter",
}

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

    # Returning paid users whose prepaid window has ended must re-purchase.
    # (This also prevents them from falling back to Free lifetime credits.)
    if enforce_limit and bool(context.get("expired_paid")):
        raise HTTPException(
            status_code=403,
            detail="Your pre-paid period has ended. Please select a plan to continue.",
        )

    # Free trial time-gate: block access once the 7-day window has elapsed.
    if enforce_limit and bool(context.get("free_trial_expired")):
        raise HTTPException(
            status_code=403,
            detail="Your 7-day free trial has ended. Upgrade to a paid plan to continue using Cross-Border AI.",
        )

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

def validate_feature_access(context: dict, feature: str) -> None:
    """
    Check that the shop's plan includes *feature*.
    Raises HTTPException 403 with the required tier name if not entitled.
    """
    plan = context.get("plan")
    plan_name = str(getattr(plan, "name", "") or context.get("effective_plan_name") or "Free")
    ent = get_entitlements(plan_name)

    if not ent.get(feature, False):
        required = get_required_tier(feature) or "a higher"
        raise HTTPException(
            status_code=403,
            detail=f"This feature requires the {required} plan. You are on {plan_name}.",
        )


def validate_agent_action_access(context: dict, action: str) -> None:
    """
    Gate an ad-hoc agent action based on the plan entitlements.
    """
    feature = _ACTION_TO_FEATURE.get(action)
    if feature:
        validate_feature_access(context, feature)


def validate_image_credits(context: dict) -> None:
    """
    Check that the shop has remaining image credits (ad-hoc usage).
    Raises 403 if no credits left.
    """
    plan = context.get("plan")
    shop = context.get("shop")
    plan_name = str(getattr(plan, "name", "") or "Free")
    ent = get_entitlements(plan_name)

    if not ent.get("image_refinement_adhoc", False):
        required = get_required_tier("image_refinement_adhoc") or "Pro"
        raise HTTPException(
            status_code=403,
            detail=f"Image generation requires the {required} plan.",
        )

    limit_type = ent.get("image_limit_type", "monthly")
    limit = int(ent.get("image_generation_limit", 0))
    if limit == -1:
        return
    if limit == 0:
        raise HTTPException(status_code=403, detail="Your plan has no image credits.")

    if limit_type == "lifetime":
        remaining = int(getattr(shop, "lifetime_image_credits_remaining", 0) or 0)
    else:
        remaining = max(0, limit - int(getattr(shop, "monthly_image_generations_used", 0) or 0))

    if remaining <= 0:
        raise HTTPException(
            status_code=403,
            detail="You've used all your image credits for this period.",
        )


def validate_mission_access(context: dict) -> None:
    """
    Check that the shop can create a new mission.
    Raises 403 if missions are not in the plan or the limit is reached.
    """
    plan = context.get("plan")
    shop = context.get("shop")
    plan_name = str(getattr(plan, "name", "") or "Free")
    ent = get_entitlements(plan_name)

    if not ent.get("missions", False):
        raise HTTPException(status_code=403, detail="Missions are not available on your plan.")

    limit = int(ent.get("mission_limit", 0))
    if limit == -1:
        return
    if limit == 0:
        raise HTTPException(status_code=403, detail="Missions are not available on your plan.")

    limit_type = ent.get("mission_limit_type", "monthly")
    if limit_type == "lifetime":
        remaining = int(getattr(shop, "lifetime_missions_remaining", 0) or 0)
    else:
        remaining = max(0, limit - int(getattr(shop, "monthly_missions_used", 0) or 0))

    if remaining <= 0:
        kind = "lifetime" if limit_type == "lifetime" else "monthly"
        raise HTTPException(
            status_code=403,
            detail=f"You've reached your {kind} mission limit ({limit}). Upgrade for more.",
        )


def validate_rewrite_request(request_body: dict):
    """
    Additional validation for the request body beyond Pydantic types.
    """
    if not request_body.get("japanese_description") or not request_body["japanese_description"].strip():
        raise HTTPException(status_code=422, detail="Japanese description cannot be empty or whitespace only.")
    
    if len(request_body["japanese_description"]) > 5000:
        raise HTTPException(status_code=422, detail="Description too long (max 5000 characters).")



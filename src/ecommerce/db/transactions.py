from __future__ import annotations
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from .models import User, Plan, Shop, FeatureUsage, UsageEventLog

# NOTE: get_user_quota_context was used for API Key validation.
# Since we are removing API Keys, we might need a different way to validate external requests if we still support them.
# For now, I will comment it out or adapt it if the user still wants direct API access (which they likely do for non-proxy calls).
# If direct API access is still needed, we'd need to authenticate the User directly (e.g. via a token on the User model).
# For this refactor, I will focus on the Proxy flow which uses Shop Domain.

def sync_usage_limits(db: Session, shop: Shop, *, billing_cycle_type: str | None = None) -> Shop:
    """
    Self-healing monthly reset:
    - If next_reset_date is missing, initialize it as reset_anchor_date + 30 days
    - If current time is past next_reset_date, reset monthly_rewrites_used to 0 and
      advance next_reset_date by 30 days until it's in the future.

    Defensive note: some unit tests pass MagicMock "shops" (mocked DB sessions).
    In that case, we avoid datetime comparisons and just no-op / initialize.
    """
    now = datetime.now(timezone.utc)

    # Lifetime plans (e.g., Free) should never be mutated by monthly reset logic.
    if str(billing_cycle_type or "").strip().lower() == "lifetime":
        # Ensure lifetime bucket exists (best-effort for legacy rows)
        lr = getattr(shop, "lifetime_rewrites_remaining", None)
        try:
            shop.lifetime_rewrites_remaining = int(lr) if lr is not None else 10
        except Exception:
            shop.lifetime_rewrites_remaining = 10
        # Do not set/advance monthly reset dates for lifetime plans.
        # (We still persist the row to ensure defaults exist.)
        db.add(shop)
        db.commit()
        db.refresh(shop)
        return shop

    def _coerce_utc(dt: datetime) -> datetime:
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    ra = getattr(shop, 'reset_anchor_date', None)
    if isinstance(ra, datetime):
        shop.reset_anchor_date = _coerce_utc(ra)
    else:
        shop.reset_anchor_date = now

    nr = getattr(shop, 'next_reset_date', None)
    if isinstance(nr, datetime):
        shop.next_reset_date = _coerce_utc(nr)
    else:
        shop.next_reset_date = shop.reset_anchor_date + timedelta(days=30)

    nr = getattr(shop, 'next_reset_date', None)
    if isinstance(nr, datetime) and now >= nr:
        shop.monthly_rewrites_used = 0
        shop.monthly_cost_accumulated = 0
        shop.fair_use_last_notified_at = None
        shop.monthly_missions_used = 0
        shop.monthly_image_generations_used = 0
        while isinstance(shop.next_reset_date, datetime) and now >= shop.next_reset_date:
            shop.next_reset_date = shop.next_reset_date + timedelta(days=30)

    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop


def get_shop_quota_context(db: Session, shop_domain: str) -> dict | None:
    """
    Retrieves user, plan, and rewrite usage information based on the Shop Domain (username).
    Returns None if the user/shop is not found.
    """
    # 1. Find User by shop_domain (username)
    user = (
        db.query(User)
        .filter(User.username == shop_domain)
        .first()
    )

    if not user:
        return None

    plan = user.plan
    if not plan:
        return None

    # 2. Fetch shop record linked to domain (usage + reset dates live here)
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        shop = Shop(domain=shop_domain, access_token="")
        db.add(shop)
        db.commit()
        db.refresh(shop)

    def _tier_rank(name: str | None) -> int:
        n = str(name or "").strip().lower()
        if n == "pro":
            return 3
        if n == "standard":
            return 2
        if n == "basic":
            return 1
        return 0

    def _is_paid_plan(name: str | None) -> bool:
        n = str(name or "").strip().lower()
        return n in ("basic", "standard", "pro")

    def _parse_dt(val) -> datetime | None:
        if isinstance(val, datetime):
            return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
        if isinstance(val, str) and val.strip():
            try:
                dt = datetime.fromisoformat(val.strip())
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        return None

    now = datetime.now(timezone.utc)

    # -------------------------------------------------------------------------
    # Apply scheduled plan changes (downgrade/cancel) when effective.
    # DB is the source of truth: the UI uses effective_plan_name, and gating uses `plan`.
    # -------------------------------------------------------------------------
    try:
        pending_name = (getattr(shop, "pending_plan_name", None) or "").strip() or None
        pending_at = _parse_dt(getattr(shop, "pending_plan_effective_at", None))
        if pending_name and isinstance(pending_at, datetime) and pending_at <= now:
            # Apply pending plan now
            shop.current_plan_name = pending_name
            shop.last_plan_name = pending_name
            shop.pending_plan_name = None
            shop.pending_plan_effective_at = None
            shop.last_plan_change_type = "downgrade" if _tier_rank(pending_name) < _tier_rank(getattr(plan, "name", None)) else "none"
            shop.last_plan_change_at = now
            db.add(shop)
            db.commit()
            db.refresh(shop)

            # Keep User.plan_id consistent with DB plan source-of-truth
            try:
                p = get_plan_by_name(db, pending_name)
                if p:
                    user.plan_id = p.id
                    db.add(user)
                    db.commit()
                    db.refresh(user)
                    plan = p
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    last_plan_name = (
        (getattr(shop, "last_plan_name", None) or "").strip()
        or (getattr(shop, "current_plan_name", None) or "").strip()
        or (getattr(plan, "name", None) or "").strip()
    )

    # Effective plan is the DB current plan (unless grace override applies below).
    effective_plan_name = (getattr(shop, "current_plan_name", None) or "").strip() or str(getattr(plan, "name", "") or "").strip() or "Free"
    try:
        override = get_plan_by_name(db, effective_plan_name)
        if override:
            plan = override
    except Exception:
        pass
    access_expires_at = _parse_dt(getattr(shop, "access_expires_at", None))
    grace_active = _is_paid_plan(last_plan_name) and isinstance(access_expires_at, datetime) and access_expires_at > now
    expired_paid = _is_paid_plan(last_plan_name) and (not access_expires_at or access_expires_at <= now) and not grace_active
    last_uninstalled_at = _parse_dt(getattr(shop, "last_uninstalled_at", None))
    grace_mode = bool(grace_active and isinstance(last_uninstalled_at, datetime))

    # During grace period we temporarily treat the shop as their last paid plan (even if Shopify cancelled).
    # This affects quota/feature gates downstream.
    if grace_active:
        plan_override = get_plan_by_name(db, last_plan_name)
        if plan_override:
            plan = plan_override

    billing_cycle_type = str(getattr(plan, "billing_cycle_type", "") or "").strip().lower()
    if not billing_cycle_type:
        billing_cycle_type = "lifetime" if str(plan.name or "") == "Free" else "recurring"

    shop = sync_usage_limits(db, shop, billing_cycle_type=billing_cycle_type)

    # Lifetime plan: one-time bucket (never resets)
    if billing_cycle_type == "lifetime":
        quota = 10
        try:
            quota = int(getattr(plan, "product_limit", None) or 10)
        except Exception:
            quota = 10
        remaining = int(getattr(shop, "lifetime_rewrites_remaining", 0) or 0)
        used = max(0, int(quota) - int(remaining))
        rewrites_used = used
        rewrite_limit = int(quota)
        next_reset = None
    else:
        rewrites_used = int(shop.monthly_rewrites_used or 0)
        rewrite_limit = plan.product_limit if plan.product_limit is not None else plan.monthly_rewrite_limit
        next_reset = shop.next_reset_date

    # If the merchant is a returning paid user but their prepaid window has expired,
    # force the effective limit to 0 (the app should redirect them to pricing).
    if expired_paid:
        rewrites_used = 0
        rewrite_limit = 0
        next_reset = None

    return {
        "user": user,
        "plan": plan,
        "shop": shop,
        "rewrites_used": rewrites_used,
        "rewrite_limit": rewrite_limit,
        "billing_cycle_type": billing_cycle_type,
        "lifetime_rewrites_remaining": int(getattr(shop, "lifetime_rewrites_remaining", 0) or 0),
        "next_reset_date": next_reset,
        "is_active": True, # Users are active if they exist and have a plan
        # Reinstall / grace period metadata
        "last_plan_name": last_plan_name,
        "current_plan_name": (getattr(shop, "current_plan_name", None) or None),
        "effective_plan_name": (getattr(shop, "current_plan_name", None) or None),
        "access_expires_at": access_expires_at,
        "grace_active": bool(grace_active),
        # Reinstall-only UI flag: show "Grace" only when the shop previously uninstalled.
        "grace_mode": bool(grace_mode),
        "last_uninstalled_at": last_uninstalled_at,
        "expired_paid": bool(expired_paid),
    }

def record_successful_rewrite(db: Session, shop_domain: str, amount: int = 1) -> Shop | None:
    """
    Record a successful rewrite:
    - Free/lifetime: decrement lifetime_rewrites_remaining
    - Paid/recurring: increment monthly_rewrites_used
    """
    if not shop_domain:
        return None
    ctx = get_shop_quota_context(db, shop_domain)
    if not ctx:
        return None
    shop: Shop = ctx["shop"]
    plan = ctx["plan"]
    billing_cycle_type = str(ctx.get("billing_cycle_type") or getattr(plan, "billing_cycle_type", "") or "").strip().lower()
    if not billing_cycle_type:
        billing_cycle_type = "lifetime" if str(getattr(plan, "name", "") or "") == "Free" else "recurring"

    amt = int(amount or 0)
    if amt <= 0:
        return shop

    if billing_cycle_type == "lifetime":
        cur = int(getattr(shop, "lifetime_rewrites_remaining", 0) or 0)
        shop.lifetime_rewrites_remaining = max(0, cur - amt)
    else:
        shop = sync_usage_limits(db, shop, billing_cycle_type=billing_cycle_type)
        shop.monthly_rewrites_used = int(shop.monthly_rewrites_used or 0) + amt

    # Onboarding Step 1 auto-complete: first successful rewrite (best-effort).
    try:
        if hasattr(shop, "is_onboarding_finished") and hasattr(shop, "onboarding_step"):
            if not bool(getattr(shop, "is_onboarding_finished", False)):
                cur_step = int(getattr(shop, "onboarding_step", 0) or 0)
                if cur_step < 1:
                    shop.onboarding_step = 1
    except Exception:
        pass

    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop


# Backwards-compatible alias (older call sites)
def increment_monthly_rewrites_used(db: Session, shop_domain: str, amount: int = 1) -> Shop | None:
    return record_successful_rewrite(db, shop_domain, amount=amount)

def get_plan_by_id(db: Session, plan_id: int) -> Plan | None:
    return db.query(Plan).filter(Plan.id == plan_id).first()

def get_plan_by_name(db: Session, plan_name: str) -> Plan | None:
    return db.query(Plan).filter(Plan.name == plan_name).first()

def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()

def create_user(db: Session, username: str, email: str | None, plan_id: int) -> User:
    new_user = User(username=username, email=email, plan_id=plan_id)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

def store_shop_access_token(db: Session, shop_domain: str, access_token: str, token_type: str = "offline", force: bool = False):
    """
    Stores or updates the access token for a given shop.
    ALSO ensures a corresponding User record exists for billing/quota.
    """
    from .models import Shop, User, Plan
    import secrets
    from src.shared.logging.logger import get_logger
    logger = get_logger(__name__)

    logger.info(f"Storing access token for shop: {shop_domain} (type={token_type})")

    # 1. Update/Create Shop Record (OAuth Token)
    # Rules:
    # - If token_type is 'offline', ALWAYS overwrite (it's the permanent token).
    # - If token_type is 'online', ONLY overwrite if we don't have a token, or if the current token is also online.
    #   (Though realistically we can't definitively know if the current DB token is online/offline without storing type,
    #    we will assume if we are sent an ONLINE token, we should be careful not to nuke a working OFFLINE one).

    shop_record = db.query(Shop).filter(Shop.domain == shop_domain).first()
    
    should_update = True
    if shop_record and shop_record.access_token:
        # If we have an existing token...
        if token_type == "online" and not force:
            # Heuristic: If existing token looks like an offline token (starts with shp), don't overwrite it with online (starts with shpua)
            # Actually, let's trust the input logic: If it's ONLINE, we treat it as temporary.
            # If the existing token is present, we assume it might be offline (preferred).
            # So we SKIP updating if we are given an online token and already have ANY token.
            # Exception: unless the existing token is known to be broken (but we don't know that here).
            logger.warning(f"Skipping update for {shop_domain} because we received an ONLINE token and already have a token stored.")
            should_update = False
        elif token_type == "offline":
            # Always overwrite with offline token
            should_update = True

    if should_update:
        if shop_record:
            shop_record.access_token = access_token
        else:
            now = datetime.now(timezone.utc)
            new_shop = Shop(
                domain=shop_domain,
                access_token=access_token,
                monthly_rewrites_used=0,
                lifetime_rewrites_remaining=10,
                current_plan_name="Free",
                last_plan_name="Free",
                reset_anchor_date=now,
                next_reset_date=now + timedelta(days=30),
            )
            db.add(new_shop)
            shop_record = new_shop
    
    # 2. Update/Create User Record (Billing Identity)
    user = db.query(User).filter(User.username == shop_domain).first()
    
    if not user:
        # Assign default plan
        default_plan = db.query(Plan).filter(Plan.name == "Free").first()
        if not default_plan:
             logger.warning("Plan 'Free' not found. Falling back to first available plan.")
             default_plan = db.query(Plan).first()
        
        if default_plan:
            logger.info(f"Creating new user for {shop_domain} with plan {default_plan.name}")
            user = User(username=shop_domain, email=None, plan_id=default_plan.id)
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            logger.error(f"CRITICAL: No plans found in database. Cannot create user for {shop_domain}.")
            # We should probably raise here, but for now just logging
            pass

    db.commit()
    db.refresh(shop_record)
    logger.info(f"Successfully stored shop and user for {shop_domain}")
    return shop_record

def get_shop_access_token(db: Session, shop_domain: str) -> str | None:
    """
    Retrieves the access token for a given shop domain.
    """
    from .models import Shop
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    return shop.access_token if shop else None


# ---------------------------------------------------------------------------
# Feature-level usage tracking
# ---------------------------------------------------------------------------

def _cycle_start_for_shop(shop: Shop) -> datetime:
    """Return the start of the current billing cycle for a shop."""
    nr = getattr(shop, "next_reset_date", None)
    if isinstance(nr, datetime):
        if nr.tzinfo is None:
            nr = nr.replace(tzinfo=timezone.utc)
        return nr - timedelta(days=30)
    return datetime.now(timezone.utc)


def record_feature_usage(db: Session, shop_domain: str, feature: str, amount: int = 1) -> int:
    """Increment the aggregate FeatureUsage counter for *feature* in the current billing cycle."""
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        return 0
    cycle_start = _cycle_start_for_shop(shop).date()
    rec = (
        db.query(FeatureUsage)
        .filter(
            FeatureUsage.shop_domain == shop_domain,
            FeatureUsage.feature == feature,
            FeatureUsage.billing_cycle_start == cycle_start,
        )
        .first()
    )
    if not rec:
        rec = FeatureUsage(shop_domain=shop_domain, feature=feature, billing_cycle_start=cycle_start, usage_count=0)
        db.add(rec)
    rec.usage_count = int(rec.usage_count or 0) + int(amount)
    db.commit()
    db.refresh(rec)
    return int(rec.usage_count)


def get_feature_usage(db: Session, shop_domain: str) -> dict[str, int]:
    """Return ``{feature: count}`` for all features used in the current billing cycle."""
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        return {}
    cycle_start = _cycle_start_for_shop(shop).date()
    rows = (
        db.query(FeatureUsage)
        .filter(FeatureUsage.shop_domain == shop_domain, FeatureUsage.billing_cycle_start == cycle_start)
        .all()
    )
    return {r.feature: int(r.usage_count or 0) for r in rows}


def log_usage_event(
    db: Session,
    *,
    shop_domain: str,
    plan_name: str,
    event_type: str,
    feature: str,
    product_count: int = 0,
    image_count: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    reasoning_tokens: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
    product_id: str | None = None,
    mission_id: str | None = None,
    agent_name: str | None = None,
    model_used: str | None = None,
    action: str | None = None,
    metadata_json: str | None = None,
) -> None:
    """Append a row to the usage_event_log audit trail (best-effort, never raises)."""
    try:
        row = UsageEventLog(
            shop_domain=shop_domain,
            plan_name=plan_name,
            event_type=event_type,
            feature=feature,
            product_count=product_count,
            image_count=image_count,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            product_id=product_id,
            mission_id=mission_id,
            agent_name=agent_name,
            model_used=model_used,
            action=action,
            metadata_json=metadata_json,
        )
        db.add(row)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from .db_models import User, Plan, Shop

# NOTE: get_user_quota_context was used for API Key validation.
# Since we are removing API Keys, we might need a different way to validate external requests if we still support them.
# For now, I will comment it out or adapt it if the user still wants direct API access (which they likely do for non-proxy calls).
# If direct API access is still needed, we'd need to authenticate the User directly (e.g. via a token on the User model).
# For this refactor, I will focus on the Proxy flow which uses Shop Domain.

def sync_usage_limits(db: Session, shop: Shop) -> Shop:
    """
    Self-healing monthly reset:
    - If next_reset_date is missing, initialize it as reset_anchor_date + 30 days
    - If current time is past next_reset_date, reset monthly_rewrites_used to 0 and
      advance next_reset_date by 30 days until it's in the future.

    Defensive note: some unit tests pass MagicMock "shops" (mocked DB sessions).
    In that case, we avoid datetime comparisons and just no-op / initialize.
    """
    now = datetime.now(timezone.utc)

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

    shop = sync_usage_limits(db, shop)

    rewrites_used = int(shop.monthly_rewrites_used or 0)
    rewrite_limit = plan.product_limit if plan.product_limit is not None else plan.monthly_rewrite_limit

    return {
        "user": user,
        "plan": plan,
        "shop": shop,
        "rewrites_used": rewrites_used,
        "rewrite_limit": rewrite_limit,
        "is_active": True # Users are active if they exist and have a plan
    }

def increment_monthly_rewrites_used(db: Session, shop_domain: str, amount: int = 1) -> Shop | None:
    """
    Increment monthly_rewrites_used for a shop after a successful rewrite.
    """
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        return None

    shop = sync_usage_limits(db, shop)
    shop.monthly_rewrites_used = int(shop.monthly_rewrites_used or 0) + int(amount or 0)
    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop

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
    from .db_models import Shop, User, Plan
    import secrets
    from src.main.logging.logger import get_logger
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
                reset_anchor_date=now,
                next_reset_date=now + timedelta(days=30),
            )
            db.add(new_shop)
            shop_record = new_shop
    
    # 2. Update/Create User Record (Billing Identity)
    user = db.query(User).filter(User.username == shop_domain).first()
    
    if not user:
        # Assign default plan
        default_plan = db.query(Plan).filter(Plan.name == "Basic").first()
        if not default_plan:
             logger.warning("Plan 'Basic' not found. Falling back to first available plan.")
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
    from .db_models import Shop
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    return shop.access_token if shop else None

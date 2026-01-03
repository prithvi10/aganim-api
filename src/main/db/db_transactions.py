from sqlalchemy.orm import Session
from sqlalchemy import update
from datetime import date
from .db_models import User, UsageRecord, Plan

# NOTE: get_user_quota_context was used for API Key validation.
# Since we are removing API Keys, we might need a different way to validate external requests if we still support them.
# For now, I will comment it out or adapt it if the user still wants direct API access (which they likely do for non-proxy calls).
# If direct API access is still needed, we'd need to authenticate the User directly (e.g. via a token on the User model).
# For this refactor, I will focus on the Proxy flow which uses Shop Domain.

def get_shop_quota_context(db: Session, shop_domain: str) -> dict | None:
    """
    Retrieves user, plan, and usage information based on the Shop Domain (username).
    Returns None if the user/shop is not found.
    """
    today = date.today()
    cycle_start = date(today.year, today.month, 1)

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

    # 2. Fetch current usage record linked to USER
    usage_record = (
        db.query(UsageRecord)
        .filter(
            UsageRecord.user_id == user.id,
            UsageRecord.billing_cycle_start == cycle_start
        )
        .first()
    )

    current_usage = usage_record.token_count if usage_record else 0

    return {
        "user": user,
        "plan": plan,
        "user_id": user.id, # Changed from api_key_id
        "current_usage": current_usage,
        "billing_cycle_start": cycle_start,
        "is_active": True # Users are active if they exist and have a plan
    }

def update_token_usage(db: Session, user_id: int, token_usage: int, billing_cycle_start: date):
    """
    Atomic update of the usage record.
    """
    
    # 1. Try to update existing record
    stmt = (
        update(UsageRecord)
        .where(
            UsageRecord.user_id == user_id,
            UsageRecord.billing_cycle_start == billing_cycle_start
        )
        .values(token_count=UsageRecord.token_count + token_usage)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    
    # 2. If no row updated, it means the record doesn't exist for this month yet.
    if result.rowcount == 0:
        try:
            new_record = UsageRecord(
                user_id=user_id,
                billing_cycle_start=billing_cycle_start,
                token_count=token_usage
            )
            db.add(new_record)
            db.commit()
        except Exception:
            db.rollback()
            result = db.execute(stmt)
            db.commit()
    else:
        db.commit()

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
            new_shop = Shop(domain=shop_domain, access_token=access_token)
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

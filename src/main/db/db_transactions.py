from sqlalchemy.orm import Session
from sqlalchemy import update
from datetime import date
from .db_models import User, APIKey, UsageRecord, Plan

def get_user_quota_context(db: Session, key_hash: str) -> dict | None:
    """
    Retrieves user, plan, and usage information based on the API Key hash.
    Returns None if the key is invalid or not found.
    Does NOT verify quota limits or raise HTTP exceptions.
    """
    today = date.today()
    cycle_start = date(today.year, today.month, 1)

    # Query for the key
    api_key_record = (
        db.query(APIKey)
        .filter(APIKey.key_hash == key_hash)
        .first()
    )

    if not api_key_record:
        return None

    user = api_key_record.user
    if not user:
         # Orphaned key scenario
         return None

    plan = user.plan
    if not plan:
         return None

    # Fetch current usage record
    usage_record = (
        db.query(UsageRecord)
        .filter(
            UsageRecord.api_key_id == api_key_record.id,
            UsageRecord.billing_cycle_start == cycle_start
        )
        .first()
    )

    current_usage = usage_record.token_count if usage_record else 0

    return {
        "user": user,
        "plan": plan,
        "api_key_id": api_key_record.id,
        "current_usage": current_usage,
        "billing_cycle_start": cycle_start,
        "is_active": api_key_record.is_active
    }

def get_shop_quota_context(db: Session, shop_domain: str) -> dict | None:
    """
    Retrieves user, plan, and usage information based on the Shop Domain (username).
    Returns None if the user/shop is not found or has no active API key.
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

    # 2. Find ACTIVE API Key
    # We prioritize finding *any* active key.
    api_key_record = (
        db.query(APIKey)
        .filter(
            APIKey.user_id == user.id,
            APIKey.is_active == True
        )
        .order_by(APIKey.created_at.desc()) # Use most recent if multiple
        .first()
    )

    if not api_key_record:
        return None

    plan = user.plan
    if not plan:
        return None

    # 3. Fetch current usage record
    usage_record = (
        db.query(UsageRecord)
        .filter(
            UsageRecord.api_key_id == api_key_record.id,
            UsageRecord.billing_cycle_start == cycle_start
        )
        .first()
    )

    current_usage = usage_record.token_count if usage_record else 0

    return {
        "user": user,
        "plan": plan,
        "api_key_id": api_key_record.id,
        "current_usage": current_usage,
        "billing_cycle_start": cycle_start,
        "is_active": api_key_record.is_active
    }

def update_token_usage(db: Session, api_key_id: int, token_usage: int, billing_cycle_start: date):
    """
    Atomic update of the usage record.
    If record doesn't exist, create it (upsert logic needed or check-then-create).
    To be safe and atomic, we often use:
      UPDATE usage_records SET token_count = token_count + :usage 
      WHERE api_key_id = :id AND billing_cycle_start = :date
    """
    
    # 1. Try to update existing record
    stmt = (
        update(UsageRecord)
        .where(
            UsageRecord.api_key_id == api_key_id,
            UsageRecord.billing_cycle_start == billing_cycle_start
        )
        .values(token_count=UsageRecord.token_count + token_usage)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    
    # 2. If no row updated, it means the record doesn't exist for this month yet.
    if result.rowcount == 0:
        # Create new record
        # Note: There's a tiny race condition here if two reqs come in at exact same time 
        # for a NEW month. Handle with unique constraint/integrity error in real prod.
        try:
            new_record = UsageRecord(
                api_key_id=api_key_id,
                billing_cycle_start=billing_cycle_start,
                token_count=token_usage
            )
            db.add(new_record)
            db.commit()
        except Exception:
            db.rollback()
            # If insert failed (race condition), try update again
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

def create_api_key_record(db: Session, user_id: int, key_hash: str) -> APIKey:
    new_key = APIKey(user_id=user_id, key_hash=key_hash)
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    return new_key

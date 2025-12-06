from sqlalchemy.orm import Session
from sqlalchemy import update
from fastapi import HTTPException
from datetime import date
from .db_models import User, APIKey, UsageRecord, Plan

def verify_api_key_and_quota(db: Session, key_hash: str) -> dict:
    """
    1. Lookup APIKey by hash.
    2. Verify Key is Active.
    3. Join User and Plan to get Quota.
    4. Join/Fetch UsageRecord for current billing cycle.
    5. Check if Usage < Quota.
    """
    # We'll assume billing cycle starts on the 1st of the month for simplicity
    # In a real app, this might be user-specific based on subscription date.
    today = date.today()
    cycle_start = date(today.year, today.month, 1)

    # Perform a joined query to fetch everything in one go if possible, 
    # or use relationship loading. 
    # Here we query APIKey and eagerly load user, plan, and current usage.
    
    # Query for the key
    api_key_record = (
        db.query(APIKey)
        .filter(APIKey.key_hash == key_hash)
        .first()
    )

    if not api_key_record:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    if not api_key_record.is_active:
        raise HTTPException(status_code=403, detail="API Key is inactive")

    user = api_key_record.user
    if not user:
         raise HTTPException(status_code=500, detail="Orphaned API Key (No User)")

    plan = user.plan
    if not plan:
         # Fallback or error if no plan assigned. 
         # Assuming a default plan should exist or user must have one.
         raise HTTPException(status_code=403, detail="No subscription plan found")

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
    quota_limit = plan.monthly_token_quota

    if current_usage >= quota_limit:
        raise HTTPException(status_code=429, detail="Monthly token quota exceeded")

    # Return context for the controller (e.g. to use in write operation)
    return {
        "user": user,
        "plan": plan,
        "api_key_id": api_key_record.id,
        "current_usage": current_usage,
        "billing_cycle_start": cycle_start
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


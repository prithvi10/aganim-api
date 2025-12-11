import secrets
from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.main.db import db_transactions
from src.main.api.models import OnboardingRequest, OnboardingResponse
from src.main.security.security import hash_api_key
from src.main.logging.logger import get_logger

logger = get_logger(__name__)

def onboard_user(db: Session, request: OnboardingRequest) -> OnboardingResponse:
    """
    Handles the full onboarding flow for a new user:
    1. Validates the plan.
    2. Checks if the user already exists.
    3. Creates the User record.
    4. Generates and stores a new API Key.
    5. Returns the user details and the raw API Key.
    """
    
    # 1. Validate Plan
    plan = db_transactions.get_plan_by_id(db, request.plan_id)
    if not plan:
        logger.warning(f"Onboarding failed: Invalid Plan ID {request.plan_id}")
        raise HTTPException(status_code=400, detail=f"Invalid Plan ID: {request.plan_id}")

    # 2. Check if User Exists
    existing_user = db_transactions.get_user_by_username(db, request.username)
    if existing_user:
        logger.warning(f"Onboarding failed: User {request.username} already exists")
        raise HTTPException(status_code=409, detail=f"User already exists: {request.username}")

    # 3. Create User
    try:
        new_user = db_transactions.create_user(
            db=db,
            username=request.username,
            email=request.email,
            plan_id=plan.id
        )
        logger.info(f"Created new user: {new_user.username} with plan {plan.name}")
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user record.")

    # 4. Generate & Store API Key
    # Generate a random 32-byte URL-safe string
    raw_api_key = secrets.token_urlsafe(32)
    hashed_key = hash_api_key(raw_api_key)
    
    try:
        db_transactions.create_api_key_record(db, new_user.id, hashed_key)
        logger.info(f"Generated API key for user: {new_user.username}")
    except Exception as e:
        logger.error(f"Failed to create API key record: {e}")
        # Note: In a production system with transaction management, we would rollback here.
        # Since our DB helpers currently auto-commit, we would need to manually cleanup 
        # or refactor the DB layer to support session-managed transactions better.
        raise HTTPException(status_code=500, detail="Failed to generate API key.")

    # 5. Return Response
    return OnboardingResponse(
        user_id=new_user.id,
        username=new_user.username,
        plan_name=plan.name,
        api_key=raw_api_key
    )


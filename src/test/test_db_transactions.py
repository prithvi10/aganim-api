import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from src.main.db.database import Base
from src.main.db.db_models import User, Plan, APIKey, UsageRecord
from src.main.db.db_transactions import verify_api_key_and_quota, update_token_usage
from src.main.security.security import hash_api_key

# Use in-memory SQLite for testing transactions
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    # Setup basic data
    plan = Plan(name="Test Plan", monthly_token_quota=1000, max_request_rate=10)
    db.add(plan)
    db.commit()
    
    user = User(username="test_user", plan_id=plan.id)
    db.add(user)
    db.commit()
    
    raw_key = "valid_key"
    key_hash = hash_api_key(raw_key)
    api_key = APIKey(user_id=user.id, key_hash=key_hash, is_active=True)
    db.add(api_key)
    db.commit()
    
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

def test_verify_api_key_valid(db_session):
    """Should return context when key is valid and within quota."""
    key_hash = hash_api_key("valid_key")
    context = verify_api_key_and_quota(db_session, key_hash)
    
    assert context["user"].username == "test_user"
    assert context["plan"].name == "Test Plan"
    assert context["current_usage"] == 0

def test_verify_api_key_invalid(db_session):
    """Should raise 401 for invalid key."""
    with pytest.raises(HTTPException) as exc:
        verify_api_key_and_quota(db_session, "invalid_hash")
    assert exc.value.status_code == 401

def test_verify_quota_exceeded(db_session):
    """Should raise 429 when usage exceeds quota."""
    key_hash = hash_api_key("valid_key")
    
    # Manually insert high usage
    api_key = db_session.query(APIKey).filter_by(key_hash=key_hash).first()
    today = date.today()
    cycle_start = date(today.year, today.month, 1)
    
    # Plan quota is 1000
    usage = UsageRecord(
        api_key_id=api_key.id,
        billing_cycle_start=cycle_start,
        token_count=1001
    )
    db_session.add(usage)
    db_session.commit()
    
    with pytest.raises(HTTPException) as exc:
        verify_api_key_and_quota(db_session, key_hash)
    assert exc.value.status_code == 429

def test_update_token_usage_new_record(db_session):
    """Should create a new usage record if none exists."""
    key_hash = hash_api_key("valid_key")
    api_key = db_session.query(APIKey).filter_by(key_hash=key_hash).first()
    cycle_start = date(2023, 1, 1)
    
    update_token_usage(db_session, api_key.id, 50, cycle_start)
    
    record = db_session.query(UsageRecord).filter_by(
        api_key_id=api_key.id, 
        billing_cycle_start=cycle_start
    ).first()
    
    assert record is not None
    assert record.token_count == 50

def test_update_token_usage_existing_record(db_session):
    """Should increment existing usage record."""
    key_hash = hash_api_key("valid_key")
    api_key = db_session.query(APIKey).filter_by(key_hash=key_hash).first()
    cycle_start = date(2023, 1, 1)
    
    # Initial
    usage = UsageRecord(
        api_key_id=api_key.id,
        billing_cycle_start=cycle_start,
        token_count=100
    )
    db_session.add(usage)
    db_session.commit()
    
    # Update
    update_token_usage(db_session, api_key.id, 50, cycle_start)
    
    # Verify
    db_session.refresh(usage)
    assert usage.token_count == 150


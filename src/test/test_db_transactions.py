import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.main.db.database import Base
from src.main.db.db_models import User, Plan, APIKey, UsageRecord
from src.main.db.db_transactions import get_user_quota_context, update_token_usage, get_shop_quota_context
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

def test_get_user_quota_context_valid(db_session):
    """Should return context when key is valid."""
    key_hash = hash_api_key("valid_key")
    context = get_user_quota_context(db_session, key_hash)
    
    assert context is not None
    assert context["user"].username == "test_user"
    assert context["plan"].name == "Test Plan"
    assert context["current_usage"] == 0

def test_get_user_quota_context_invalid(db_session):
    """Should return None for invalid key."""
    context = get_user_quota_context(db_session, "invalid_hash")
    assert context is None

def test_get_user_quota_context_usage_data(db_session):
    """Should return correct current usage."""
    key_hash = hash_api_key("valid_key")
    
    # Manually insert usage
    api_key = db_session.query(APIKey).filter_by(key_hash=key_hash).first()
    today = date.today()
    cycle_start = date(today.year, today.month, 1)
    
    usage = UsageRecord(
        api_key_id=api_key.id,
        billing_cycle_start=cycle_start,
        token_count=500
    )
    db_session.add(usage)
    db_session.commit()
    
    context = get_user_quota_context(db_session, key_hash)
    assert context["current_usage"] == 500

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

# --- New Tests for get_shop_quota_context ---

def test_get_shop_quota_context_valid(db_session):
    """Should return context when shop exists and has active key."""
    context = get_shop_quota_context(db_session, "test_user")
    
    assert context is not None
    assert context["user"].username == "test_user"
    assert context["plan"].name == "Test Plan"
    assert context["is_active"] is True

def test_get_shop_quota_context_invalid_shop(db_session):
    """Should return None if shop does not exist."""
    context = get_shop_quota_context(db_session, "non_existent_shop")
    assert context is None

def test_get_shop_quota_context_no_active_key(db_session):
    """Should return None if shop exists but has no active key."""
    # Create user without key
    plan = db_session.query(Plan).first()
    user_no_key = User(username="user_no_key", plan_id=plan.id)
    db_session.add(user_no_key)
    db_session.commit()
    
    context = get_shop_quota_context(db_session, "user_no_key")
    assert context is None
    
    # Create user with INACTIVE key
    user_inactive = User(username="user_inactive", plan_id=plan.id)
    db_session.add(user_inactive)
    db_session.commit()
    
    api_key = APIKey(user_id=user_inactive.id, key_hash="inactive", is_active=False)
    db_session.add(api_key)
    db_session.commit()
    
    context = get_shop_quota_context(db_session, "user_inactive")
    assert context is None

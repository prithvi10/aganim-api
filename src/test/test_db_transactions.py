import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.main.db.database import Base
from src.main.db.db_models import User, Plan, UsageRecord
from src.main.db.db_transactions import update_token_usage, get_shop_quota_context, get_shop_access_token, store_shop_access_token

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
    
    # No API Key setup needed anymore
    
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

def test_update_token_usage_new_record(db_session):
    """Should create a new usage record if none exists."""
    user = db_session.query(User).filter_by(username="test_user").first()
    cycle_start = date(2023, 1, 1)
    
    update_token_usage(db_session, user.id, 50, cycle_start)
    
    record = db_session.query(UsageRecord).filter_by(
        user_id=user.id, 
        billing_cycle_start=cycle_start
    ).first()
    
    assert record is not None
    assert record.token_count == 50

def test_update_token_usage_existing_record(db_session):
    """Should increment existing usage record."""
    user = db_session.query(User).filter_by(username="test_user").first()
    cycle_start = date(2023, 1, 1)
    
    # Initial
    usage = UsageRecord(
        user_id=user.id,
        billing_cycle_start=cycle_start,
        token_count=100
    )
    db_session.add(usage)
    db_session.commit()
    
    # Update
    update_token_usage(db_session, user.id, 50, cycle_start)
    
    # Verify
    db_session.refresh(usage)
    assert usage.token_count == 150

# --- New Tests for get_shop_quota_context ---

def test_get_shop_quota_context_valid(db_session):
    """Should return context when shop exists."""
    context = get_shop_quota_context(db_session, "test_user")
    
    assert context is not None
    assert context["user"].username == "test_user"
    assert context["plan"].name == "Test Plan"
    assert context["is_active"] is True

def test_get_shop_quota_context_invalid_shop(db_session):
    """Should return None if shop does not exist."""
    context = get_shop_quota_context(db_session, "non_existent_shop")
    assert context is None

def test_store_shop_access_token_create(db_session):
    """
    Should create a new Shop record AND a User record if they don't exist.
    """
    from src.main.db.db_models import User, Plan
    
    # Ensure default plan exists for the auto-creation logic
    if not db_session.query(Plan).filter_by(name="Basic Agent").first():
        db_session.add(Plan(name="Basic Agent", monthly_token_quota=1000, max_request_rate=10))
        db_session.commit()

    shop_domain = "new-shop.myshopify.com"
    token = "new_token_123"
    
    # Execute
    shop = store_shop_access_token(db_session, shop_domain, token)
    
    # 1. Verify Shop
    assert shop.domain == shop_domain
    assert shop.access_token == token
    assert shop.id is not None
    
    # 2. Verify User Created
    user = db_session.query(User).filter_by(username=shop_domain).first()
    assert user is not None
    assert user.plan is not None
    # No API Key check anymore

def test_store_shop_access_token_update(db_session):
    """Should update the access token if the Shop record exists."""
    from src.main.db.db_models import Shop
    
    shop_domain = "existing-shop.myshopify.com"
    old_token = "old_token_123"
    new_token = "new_token_456"
    
    # Create existing
    existing = Shop(domain=shop_domain, access_token=old_token)
    db_session.add(existing)
    db_session.commit()
    
    # Update
    updated = store_shop_access_token(db_session, shop_domain, new_token)
    
    assert updated.id == existing.id
    assert updated.domain == shop_domain
    assert updated.access_token == new_token

def test_get_shop_access_token_found(db_session):
    """Should return the access token if shop exists."""
    shop_domain = "token-test.myshopify.com"
    token = "secret_token"
    
    # Seed
    store_shop_access_token(db_session, shop_domain, token)
    
    # Test
    retrieved_token = get_shop_access_token(db_session, shop_domain)
    assert retrieved_token == token

def test_get_shop_access_token_not_found(db_session):
    """Should return None if shop does not exist."""
    retrieved_token = get_shop_access_token(db_session, "missing.myshopify.com")
    assert retrieved_token is None

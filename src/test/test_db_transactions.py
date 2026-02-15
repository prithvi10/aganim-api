import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.db.database import Base
from src.ecommerce.db.models import User, Plan, Shop
from src.ecommerce.db.transactions import (
    get_shop_quota_context,
    get_shop_access_token,
    store_shop_access_token,
    increment_monthly_rewrites_used,
    record_successful_rewrite,
    sync_usage_limits,
)

# Use in-memory SQLite for testing transactions
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    # Setup basic data
    plan = Plan(name="Test Plan", monthly_rewrite_limit=1000, max_request_rate=10)
    db.add(plan)
    db.commit()
    
    user = User(username="test_user", plan_id=plan.id)
    db.add(user)
    db.commit()

    # Link shop (usage lives here)
    now = datetime.now(timezone.utc)
    shop = Shop(
        domain="test_user",
        access_token="token",
        monthly_rewrites_used=0,
        reset_anchor_date=now,
        next_reset_date=now + timedelta(days=30),
    )
    db.add(shop)
    db.commit()
    
    # No API Key setup needed anymore
    
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

def test_increment_monthly_rewrites_used(db_session):
    """Should increment monthly rewrites on the Shop record."""
    shop = increment_monthly_rewrites_used(db_session, "test_user", amount=1)
    assert shop is not None
    assert shop.monthly_rewrites_used == 1

# --- New Tests for get_shop_quota_context ---

def test_get_shop_quota_context_valid(db_session):
    """Should return context when shop exists."""
    context = get_shop_quota_context(db_session, "test_user")
    
    assert context is not None
    assert context["user"].username == "test_user"
    assert context["plan"].name == "Test Plan"
    assert context["is_active"] is True
    assert context["rewrites_used"] == 0

def test_get_shop_quota_context_invalid_shop(db_session):
    """Should return None if shop does not exist."""
    context = get_shop_quota_context(db_session, "non_existent_shop")
    assert context is None

def test_store_shop_access_token_create(db_session):
    """
    Should create a new Shop record AND a User record if they don't exist.
    """
    from src.ecommerce.db.models import User, Plan
    
    # Ensure default plan exists for the auto-creation logic
    if not db_session.query(Plan).filter_by(name="Free").first():
        db_session.add(Plan(name="Free", monthly_rewrite_limit=10, product_limit=10, billing_cycle_type="lifetime", max_request_rate=10))
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
    assert user.plan.name == "Free"
    # No API Key check anymore


def test_record_successful_rewrite_free_decrements_lifetime(db_session):
    """Free/lifetime: successful rewrite decrements lifetime_rewrites_remaining and does not increment monthly usage."""
    from src.ecommerce.db.models import Plan, User, Shop
    from datetime import datetime, timedelta, timezone

    free = db_session.query(Plan).filter_by(name="Free").first()
    if not free:
        free = Plan(name="Free", monthly_rewrite_limit=10, product_limit=10, billing_cycle_type="lifetime", max_request_rate=10)
        db_session.add(free)
        db_session.commit()

    shop_domain = "free-shop.myshopify.com"
    user = db_session.query(User).filter_by(username=shop_domain).first()
    if not user:
        user = User(username=shop_domain, plan_id=free.id)
        db_session.add(user)
        db_session.commit()

    now = datetime.now(timezone.utc)
    shop = db_session.query(Shop).filter_by(domain=shop_domain).first()
    if not shop:
        shop = Shop(
            domain=shop_domain,
            access_token="token",
            monthly_rewrites_used=0,
            lifetime_rewrites_remaining=2,
            reset_anchor_date=now,
            next_reset_date=now + timedelta(days=30),
        )
        db_session.add(shop)
        db_session.commit()

    updated = record_successful_rewrite(db_session, shop_domain, amount=1)
    assert updated is not None
    assert updated.lifetime_rewrites_remaining == 1
    assert int(updated.monthly_rewrites_used or 0) == 0

def test_store_shop_access_token_update(db_session):
    """Should update the access token if the Shop record exists."""
    from src.ecommerce.db.models import Shop
    
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


def test_get_shop_quota_context_paid_grace_overrides_plan(db_session):
    """Paid grace: last_plan_name paid + access_expires_at future => grace_active True and plan overridden."""
    from src.ecommerce.db.models import Plan, User, Shop
    from src.ecommerce.db.transactions import get_shop_quota_context
    from datetime import datetime, timedelta, timezone

    # Seed plans
    if not db_session.query(Plan).filter_by(name="Basic").first():
        db_session.add(
            Plan(
                name="Basic",
                monthly_rewrite_limit=50,
                product_limit=50,
                billing_cycle_type="recurring",
                max_request_rate=10,
            )
        )
    if not db_session.query(Plan).filter_by(name="Free").first():
        db_session.add(
            Plan(
                name="Free",
                monthly_rewrite_limit=10,
                product_limit=10,
                billing_cycle_type="lifetime",
                max_request_rate=10,
            )
        )
    db_session.commit()

    free = db_session.query(Plan).filter_by(name="Free").first()
    shop_domain = "paid-grace-shop.myshopify.com"

    db_session.query(User).filter_by(username=shop_domain).delete()
    db_session.query(Shop).filter_by(domain=shop_domain).delete()
    db_session.commit()

    user = User(username=shop_domain, plan_id=free.id)
    db_session.add(user)

    now = datetime.now(timezone.utc)
    shop = Shop(
        domain=shop_domain,
        access_token="",
        last_plan_name="Basic",
        current_plan_name="Basic",
        last_uninstalled_at=now - timedelta(hours=1),
        access_expires_at=now + timedelta(days=2),
        monthly_rewrites_used=0,
        reset_anchor_date=now,
        next_reset_date=now + timedelta(days=30),
    )
    db_session.add(shop)
    db_session.commit()

    ctx = get_shop_quota_context(db_session, shop_domain)
    assert ctx is not None
    assert ctx["grace_active"] is True
    assert ctx["grace_mode"] is True
    assert ctx["expired_paid"] is False
    assert ctx["plan"].name == "Basic"
    assert int(ctx["rewrite_limit"]) == 50


def test_get_shop_quota_context_paid_expired_forces_zero_limit(db_session):
    """Paid expired: last_plan_name paid + access_expires_at past => expired_paid True and rewrite_limit forced to 0."""
    from src.ecommerce.db.models import Plan, User, Shop
    from src.ecommerce.db.transactions import get_shop_quota_context
    from datetime import datetime, timedelta, timezone

    if not db_session.query(Plan).filter_by(name="Basic").first():
        db_session.add(
            Plan(
                name="Basic",
                monthly_rewrite_limit=50,
                product_limit=50,
                billing_cycle_type="recurring",
                max_request_rate=10,
            )
        )
    if not db_session.query(Plan).filter_by(name="Free").first():
        db_session.add(
            Plan(
                name="Free",
                monthly_rewrite_limit=10,
                product_limit=10,
                billing_cycle_type="lifetime",
                max_request_rate=10,
            )
        )
    db_session.commit()

    free = db_session.query(Plan).filter_by(name="Free").first()
    shop_domain = "paid-expired-shop.myshopify.com"

    db_session.query(User).filter_by(username=shop_domain).delete()
    db_session.query(Shop).filter_by(domain=shop_domain).delete()
    db_session.commit()

    user = User(username=shop_domain, plan_id=free.id)
    db_session.add(user)

    now = datetime.now(timezone.utc)
    shop = Shop(
        domain=shop_domain,
        access_token="",
        last_plan_name="Basic",
        current_plan_name="Basic",
        access_expires_at=now - timedelta(days=1),
        monthly_rewrites_used=0,
        reset_anchor_date=now,
        next_reset_date=now + timedelta(days=30),
    )
    db_session.add(shop)
    db_session.commit()

    ctx = get_shop_quota_context(db_session, shop_domain)
    assert ctx is not None
    assert ctx["grace_active"] is False
    assert ctx["expired_paid"] is True
    assert int(ctx["rewrite_limit"]) == 0

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi.testclient import TestClient

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import Shop, User, Plan


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = SessionLocal()
    yield db
    db.close()


def test_apply_pending_plan_when_effective(db_session):
    # Seed plans
    pro = Plan(name="Pro", monthly_rewrite_limit=9999, max_request_rate=60, billing_cycle_type="recurring")
    basic = Plan(name="Basic", monthly_rewrite_limit=50, max_request_rate=60, billing_cycle_type="recurring")
    db_session.add_all([pro, basic])
    db_session.commit()

    # User currently Pro
    u = User(username="downgrade-shop.myshopify.com", plan_id=pro.id)
    db_session.add(u)
    db_session.commit()

    # Shop has pending downgrade effective in the past -> should apply
    now = datetime.now(timezone.utc)
    s = Shop(
        domain="downgrade-shop.myshopify.com",
        access_token="x",
        current_plan_name="Pro",
        last_plan_name="Pro",
        access_expires_at=now + timedelta(days=5),
        pending_plan_name="Basic",
        pending_plan_effective_at=now - timedelta(seconds=1),
    )
    db_session.add(s)
    db_session.commit()

    from src.main.db.db_transactions import get_shop_quota_context

    ctx = get_shop_quota_context(db_session, "downgrade-shop.myshopify.com")
    assert ctx is not None
    assert ctx["plan"].name == "Basic"
    assert ctx.get("effective_plan_name") == "Basic"

    # Ensure user.plan_id moved to Basic
    db_session.refresh(u)
    assert u.plan_id == basic.id


def test_webhook_schedules_downgrade_end_of_cycle(db_session, db_engine):
    # Seed plans
    pro = Plan(name="Pro", monthly_rewrite_limit=9999, max_request_rate=60, billing_cycle_type="recurring")
    basic = Plan(name="Basic", monthly_rewrite_limit=50, max_request_rate=60, billing_cycle_type="recurring")
    db_session.add_all([pro, basic])
    db_session.commit()

    now = datetime.now(timezone.utc)
    access_expires = now + timedelta(days=10)

    # Current is Pro in DB
    u = User(username="sched-shop.myshopify.com", plan_id=pro.id)
    s = Shop(
        domain="sched-shop.myshopify.com",
        access_token="x",
        current_plan_name="Pro",
        last_plan_name="Pro",
        access_expires_at=access_expires,
    )
    db_session.add_all([u, s])
    db_session.commit()

    def override_get_db():
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            # Simulate Shopify APP_SUBSCRIPTIONS_UPDATE payload with ACTIVE but lower tier name
            payload = {"app_subscription": {"name": "Basic", "status": "ACTIVE"}}
            # Bypass signature check for this unit-ish test
            from unittest.mock import patch

            with patch("src.main.api.controller.verify_webhook_signature", return_value=None):
                r = client.post(
                    "/webhooks/subscription-activated",
                    json=payload,
                    headers={"X-Shopify-Shop-Domain": "sched-shop.myshopify.com"},
                )
            assert r.status_code == 200

        # DB should have scheduled downgrade, not applied
        db2 = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()
        try:
            shop = db2.query(Shop).filter(Shop.domain == "sched-shop.myshopify.com").first()
            assert shop is not None
            assert shop.current_plan_name == "Pro"
            assert shop.pending_plan_name == "Basic"
            assert shop.pending_plan_effective_at is not None
            # Effective at end of current paid window
            # SQLite can round-trip tz-aware timestamps as naive; compare as UTC-naive.
            pe = shop.pending_plan_effective_at
            ae = access_expires
            if pe is not None and pe.tzinfo is not None:
                pe = pe.astimezone(timezone.utc).replace(tzinfo=None)
            if ae.tzinfo is not None:
                ae = ae.astimezone(timezone.utc).replace(tzinfo=None)
            assert pe is not None
            assert abs((pe - ae).total_seconds()) < 2
        finally:
            db2.close()
    finally:
        try:
            del app.dependency_overrides[get_db]
        except Exception:
            pass


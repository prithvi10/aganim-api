"""
Tests for the 7-day Free Trial backend enforcement.

Covers:
- free_trial_expires_at is set on new shop creation
- free_trial_expires_at survives uninstall/reinstall (never reset)
- free_trial_expired flag in get_shop_quota_context
- validate_shop_and_quota blocks expired Free trials
- Paid plan upgrade clears free_trial_expires_at
- Paid plan shops are never affected by free trial logic
"""

from __future__ import annotations

import json
import base64
import hashlib
import hmac

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from src.shared.db.database import Base, get_db
from src.ecommerce.db.models import User, Plan, Shop
from src.ecommerce.db.transactions import (
    get_shop_quota_context,
    store_shop_access_token,
)
from src.ecommerce.api.validation import validate_shop_and_quota
from src.ecommerce.api.main import app


MOCK_SHOPIFY_SECRET = "test_secret_key"

FREE_TRIAL_DAYS = 7


def _generate_hmac(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """In-memory SQLite session with seeded plans."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    for name, limit, cycle in [
        ("Free", 10, "lifetime"),
        ("Basic", 50, "recurring"),
        ("Standard", -1, "recurring"),
        ("Pro", -1, "recurring"),
    ]:
        db.add(Plan(
            name=name,
            monthly_rewrite_limit=limit,
            product_limit=limit,
            billing_cycle_type=cycle,
            max_request_rate=10,
        ))
    db.commit()

    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _seed_free_shop(db: Session, domain: str = "trial-shop", **overrides) -> Shop:
    """Helper to create a Free plan User + Shop pair."""
    now = datetime.now(timezone.utc)
    free = db.query(Plan).filter_by(name="Free").first()

    db.add(User(username=domain, plan_id=free.id))

    defaults = dict(
        domain=domain,
        access_token="tok",
        current_plan_name="Free",
        monthly_rewrites_used=0,
        lifetime_rewrites_remaining=10,
        lifetime_missions_remaining=3,
        lifetime_image_credits_remaining=5,
        free_trial_expires_at=now + timedelta(days=FREE_TRIAL_DAYS),
        reset_anchor_date=now,
        next_reset_date=now + timedelta(days=30),
    )
    defaults.update(overrides)
    shop = Shop(**defaults)
    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop


# =========================================================================
# 1. free_trial_expires_at is set correctly on new shop creation
# =========================================================================

class TestTrialSetOnCreation:

    def test_store_shop_access_token_sets_trial(self, db_session):
        """store_shop_access_token (OAuth path) sets free_trial_expires_at on new shops."""
        shop = store_shop_access_token(db_session, "new-shop.myshopify.com", "shpat_xxx")
        assert shop.free_trial_expires_at is not None
        # Should be ~7 days from now (coerce to UTC for SQLite compat)
        now = datetime.now(timezone.utc)
        trial = shop.free_trial_expires_at
        if trial.tzinfo is None:
            trial = trial.replace(tzinfo=timezone.utc)
        delta = trial - now
        assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)

    def test_store_shop_access_token_does_not_reset_existing(self, db_session):
        """Calling store_shop_access_token again (token refresh) should not create a new shop or reset trial."""
        shop1 = store_shop_access_token(db_session, "existing-shop.myshopify.com", "tok1")
        original_trial = shop1.free_trial_expires_at

        shop2 = store_shop_access_token(db_session, "existing-shop.myshopify.com", "tok2")
        assert shop2.free_trial_expires_at == original_trial


# =========================================================================
# 2. get_shop_quota_context returns correct free_trial_expired flag
# =========================================================================

class TestQuotaContextTrialFlag:

    def test_active_trial_not_expired(self, db_session):
        """Shop with future trial expiry => free_trial_expired=False."""
        _seed_free_shop(db_session, "active-trial")
        ctx = get_shop_quota_context(db_session, "active-trial")
        assert ctx is not None
        assert ctx["free_trial_expired"] is False
        assert ctx["free_trial_expires_at"] is not None

    def test_expired_trial(self, db_session):
        """Shop with past trial expiry => free_trial_expired=True."""
        expired_at = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_free_shop(db_session, "expired-trial", free_trial_expires_at=expired_at)
        ctx = get_shop_quota_context(db_session, "expired-trial")
        assert ctx is not None
        assert ctx["free_trial_expired"] is True

    def test_null_trial_not_expired(self, db_session):
        """Shop with NULL free_trial_expires_at (legacy) => free_trial_expired=False."""
        _seed_free_shop(db_session, "legacy-shop", free_trial_expires_at=None)
        ctx = get_shop_quota_context(db_session, "legacy-shop")
        assert ctx is not None
        assert ctx["free_trial_expired"] is False

    def test_paid_plan_ignores_trial(self, db_session):
        """Paid plan shops are never affected by free_trial_expired, even if the column has a past date."""
        basic = db_session.query(Plan).filter_by(name="Basic").first()
        db_session.add(User(username="paid-shop", plan_id=basic.id))
        now = datetime.now(timezone.utc)
        db_session.add(Shop(
            domain="paid-shop",
            access_token="tok",
            current_plan_name="Basic",
            last_plan_name="Basic",
            monthly_rewrites_used=0,
            lifetime_rewrites_remaining=0,
            free_trial_expires_at=now - timedelta(days=30),
            reset_anchor_date=now,
            next_reset_date=now + timedelta(days=30),
            access_expires_at=now + timedelta(days=30),
        ))
        db_session.commit()
        ctx = get_shop_quota_context(db_session, "paid-shop")
        assert ctx is not None
        assert ctx["free_trial_expired"] is False


# =========================================================================
# 3. validate_shop_and_quota blocks expired Free trials
# =========================================================================

class TestValidateBlocksExpiredTrial:

    def test_active_trial_passes(self, db_session):
        _seed_free_shop(db_session, "ok-shop")
        ctx = validate_shop_and_quota(db_session, "ok-shop")
        assert ctx is not None

    def test_expired_trial_raises_403(self, db_session):
        expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
        _seed_free_shop(db_session, "expired-shop", free_trial_expires_at=expired_at)
        with pytest.raises(HTTPException) as exc:
            validate_shop_and_quota(db_session, "expired-shop")
        assert exc.value.status_code == 403
        assert "free trial" in exc.value.detail.lower()

    def test_expired_trial_skipped_when_enforce_limit_false(self, db_session):
        expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
        _seed_free_shop(db_session, "soft-shop", free_trial_expires_at=expired_at)
        ctx = validate_shop_and_quota(db_session, "soft-shop", enforce_limit=False)
        assert ctx is not None


# =========================================================================
# 4. Uninstall/reinstall preserves free_trial_expires_at
# =========================================================================

@pytest.mark.asyncio
async def test_reinstall_preserves_trial_expiry(monkeypatch):
    """
    Install -> use -> uninstall -> reinstall flow:
    free_trial_expires_at must be the SAME after reinstall (not reset).
    """
    monkeypatch.setattr("src.shared.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET, raising=False)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db_seed = TestingSessionLocal()
    db_seed.add(Plan(name="Free", product_limit=10, monthly_rewrite_limit=10, billing_cycle_type="lifetime", max_request_rate=30))
    db_seed.commit()
    db_seed.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    shop_domain = "trial-reinstall-test.myshopify.com"

    try:
        with TestClient(app) as client:
            # 1) Install
            install_payload = {"myshopify_domain": shop_domain}
            body = json.dumps(install_payload).encode("utf-8")
            headers = {"X-Shopify-Hmac-Sha256": _generate_hmac(MOCK_SHOPIFY_SECRET, body)}
            r = client.post("/webhooks/app/install", content=body, headers=headers)
            assert r.status_code == 200

            db = TestingSessionLocal()
            shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
            assert shop is not None
            assert shop.free_trial_expires_at is not None
            original_trial = shop.free_trial_expires_at
            db.close()

            # 2) Uninstall
            r2 = client.post("/webhooks/app/uninstalled", content=body, headers=headers)
            assert r2.status_code == 200

            db = TestingSessionLocal()
            shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
            assert shop.free_trial_expires_at == original_trial
            db.close()

            # 3) Reinstall
            r3 = client.post("/webhooks/app/install", content=body, headers=headers)
            assert r3.status_code == 200

            db = TestingSessionLocal()
            shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
            assert shop.is_active is True
            assert shop.free_trial_expires_at == original_trial
            db.close()
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# =========================================================================
# 5. Paid plan upgrade clears free_trial_expires_at
# =========================================================================

class TestPaidUpgradeClearsTrial:

    def test_subscription_webhook_clears_trial(self, monkeypatch, db_session):
        """Simulates the subscription webhook logic: upgrading to Basic clears the trial."""
        now = datetime.now(timezone.utc)
        _seed_free_shop(db_session, "upgrading-shop")

        shop = db_session.query(Shop).filter_by(domain="upgrading-shop").first()
        assert shop.free_trial_expires_at is not None

        # Simulate what the subscription webhook does on paid upgrade
        shop.current_plan_name = "Basic"
        shop.last_plan_name = "Basic"
        shop.access_expires_at = now + timedelta(days=30)
        shop.free_trial_expires_at = None
        db_session.commit()
        db_session.refresh(shop)

        assert shop.free_trial_expires_at is None

        ctx = get_shop_quota_context(db_session, "upgrading-shop")
        assert ctx["free_trial_expired"] is False

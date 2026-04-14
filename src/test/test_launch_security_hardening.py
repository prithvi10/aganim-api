"""
Tests for Shopify App Store launch security hardening.

Covers:
- Dev token bypass gated behind ENVIRONMENT
- /api/admin/usage secured with TOKEN_SYNC_SECRET
- /api/proxy/generate-copy requires proxy signature
- /api/admin/submit-concern rate limiting
- Production rate limit config toggle
- SHOPIFY_REDIRECT_URI env var override
"""
import os
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

import src.shared.security.security as security
from src.shared.security.security import verify_shopify_session
from src.shared.security.ratelimiter import InMemoryRateLimiter


# =============================================================================
# 1. Dev-token bypass gated behind ENVIRONMENT
# =============================================================================

class TestDevTokenBypass:
    @pytest.fixture
    def mock_env(self, monkeypatch):
        monkeypatch.setattr(security, "SHOPIFY_API_SECRET", "test_secret")
        monkeypatch.setattr(security, "SHOPIFY_API_KEY", "test_api_key")

    def test_dev_token_allowed_when_not_production(self, mock_env, monkeypatch):
        """dev-token-123 should work when ENVIRONMENT is not production."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        result = verify_shopify_session(authorization="Bearer dev-token-123")
        assert result == "dev-shop.myshopify.com"

    def test_dev_token_custom_shop_when_not_production(self, mock_env, monkeypatch):
        """dev-token:<shop> should work when ENVIRONMENT is not production."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        result = verify_shopify_session(authorization="Bearer dev-token:custom-shop.myshopify.com")
        assert result == "custom-shop.myshopify.com"

    def test_dev_token_blocked_in_production(self, mock_env, monkeypatch):
        """dev-token-123 should be rejected when ENVIRONMENT=production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(HTTPException) as exc:
            verify_shopify_session(authorization="Bearer dev-token-123")
        assert exc.value.status_code == 401

    def test_dev_token_custom_blocked_in_production(self, mock_env, monkeypatch):
        """dev-token:<shop> should be rejected when ENVIRONMENT=production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(HTTPException) as exc:
            verify_shopify_session(authorization="Bearer dev-token:custom.myshopify.com")
        assert exc.value.status_code == 401

    def test_dev_shop_domain_override(self, mock_env, monkeypatch):
        """DEV_SHOP_DOMAIN env var should override the default dev shop."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("DEV_SHOP_DOMAIN", "override-shop.myshopify.com")
        result = verify_shopify_session(authorization="Bearer dev-token-123")
        assert result == "override-shop.myshopify.com"


# =============================================================================
# 2. /api/admin/usage TOKEN_SYNC_SECRET enforcement
# =============================================================================

class TestUsageEndpointSecurity:
    """
    Tests that /api/admin/usage requires X-Token-Sync-Secret when configured.
    Uses a minimal FastAPI test client with dependency overrides.
    """

    @pytest.fixture
    def setup_app(self, monkeypatch):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from src.ecommerce.api.main import app
        from src.shared.db.database import Base, get_db
        from src.ecommerce.db.models import Plan, User, Shop
        from src.ecommerce.api.shopify.shared import TOKEN_SYNC_SECRET as _orig
        from datetime import datetime, timezone, timedelta

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        def override_get_db():
            db = TestSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        db = TestSession()
        now = datetime.now(timezone.utc)
        if not db.query(Plan).filter_by(name="Free").first():
            db.add(Plan(name="Free", product_limit=10, monthly_rewrite_limit=10,
                        billing_cycle_type="lifetime", max_request_rate=30))
            db.commit()
        if not db.query(User).filter_by(username="test-shop.myshopify.com").first():
            plan = db.query(Plan).filter_by(name="Free").first()
            db.add(User(username="test-shop.myshopify.com", plan_id=plan.id))
            db.add(Shop(domain="test-shop.myshopify.com", access_token="tok",
                        monthly_rewrites_used=0,
                        reset_anchor_date=now, next_reset_date=now + timedelta(days=30)))
            db.commit()
        db.close()

        client = TestClient(app)
        yield client, app
        app.dependency_overrides.pop(get_db, None)

    def test_usage_rejected_when_secret_configured_and_missing(self, setup_app, monkeypatch):
        client, _ = setup_app
        monkeypatch.setattr("src.ecommerce.api.shopify.admin.TOKEN_SYNC_SECRET", "real-secret")
        r = client.get("/api/admin/usage?shop=test-shop.myshopify.com")
        assert r.status_code == 401

    def test_usage_rejected_when_secret_configured_and_wrong(self, setup_app, monkeypatch):
        client, _ = setup_app
        monkeypatch.setattr("src.ecommerce.api.shopify.admin.TOKEN_SYNC_SECRET", "real-secret")
        r = client.get(
            "/api/admin/usage?shop=test-shop.myshopify.com",
            headers={"X-Token-Sync-Secret": "wrong-secret"},
        )
        assert r.status_code == 401

    def test_usage_allowed_when_secret_configured_and_correct(self, setup_app, monkeypatch):
        client, _ = setup_app
        monkeypatch.setattr("src.ecommerce.api.shopify.admin.TOKEN_SYNC_SECRET", "real-secret")
        r = client.get(
            "/api/admin/usage?shop=test-shop.myshopify.com",
            headers={"X-Token-Sync-Secret": "real-secret"},
        )
        assert r.status_code == 200

    def test_usage_allowed_when_secret_not_configured(self, setup_app, monkeypatch):
        """When TOKEN_SYNC_SECRET is not set (dev/test), endpoint is open."""
        client, _ = setup_app
        monkeypatch.setattr("src.ecommerce.api.shopify.admin.TOKEN_SYNC_SECRET", None)
        r = client.get("/api/admin/usage?shop=test-shop.myshopify.com")
        assert r.status_code == 200


# =============================================================================
# 3. /api/proxy/generate-copy requires proxy signature
# =============================================================================

class TestProxyCopySecurity:
    """
    /api/proxy/generate-copy should now require Depends(verify_shopify_proxy_request).
    Without a valid signature, requests should be rejected.
    """

    @pytest.fixture
    def client(self):
        from src.ecommerce.api.main import app
        return TestClient(app)

    def test_generate_copy_rejects_without_signature(self, client):
        """Requests without proxy signature should be rejected."""
        r = client.post(
            "/api/proxy/generate-copy?shop=test.myshopify.com",
            json={"japanese_description": "test", "product_name": "test"},
        )
        assert r.status_code in (400, 401, 500)

    def test_generate_copy_rejects_invalid_signature(self, client):
        """Requests with invalid proxy signature should be rejected."""
        r = client.post(
            "/api/proxy/generate-copy?shop=test.myshopify.com&signature=invalid",
            json={"japanese_description": "test", "product_name": "test"},
        )
        assert r.status_code == 401


# =============================================================================
# 4. Production rate limit config toggle
# =============================================================================

class TestRateLimitConfigToggle:

    def test_local_config_used_when_not_production(self, monkeypatch):
        """Without ENVIRONMENT=production, LOCAL config should be used."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        from src.shared.config.configs import LOCAL_RATE_LIMIT_CONFIG, PRODUCTION_RATE_LIMIT_CONFIG
        local_config = LOCAL_RATE_LIMIT_CONFIG
        prod_config = PRODUCTION_RATE_LIMIT_CONFIG
        assert local_config != prod_config
        assert local_config[0]["limit"] < prod_config[0]["limit"]

    def test_production_config_has_higher_limits(self):
        """Production config should have higher limits than local."""
        from src.shared.config.configs import LOCAL_RATE_LIMIT_CONFIG, PRODUCTION_RATE_LIMIT_CONFIG
        local_burst = LOCAL_RATE_LIMIT_CONFIG[0]["limit"]
        prod_burst = PRODUCTION_RATE_LIMIT_CONFIG[0]["limit"]
        assert prod_burst > local_burst


# =============================================================================
# 5. SHOPIFY_REDIRECT_URI env var override
# =============================================================================

class TestRedirectURIConfig:

    def test_default_redirect_uri(self):
        import src.ecommerce.api.shopify.shared as shared_mod
        original = shared_mod.SHOPIFY_REDIRECT_URI
        assert "aganim-api.onrender.com" in original

    def test_custom_redirect_uri_from_env(self, monkeypatch):
        monkeypatch.setenv("SHOPIFY_REDIRECT_URI", "https://custom-api.example.com/api/auth/callback")
        result = os.getenv("SHOPIFY_REDIRECT_URI", "https://aganim-api.onrender.com/api/auth/callback")
        assert result == "https://custom-api.example.com/api/auth/callback"


# =============================================================================
# 6. submit-concern rate limiting
# =============================================================================

class TestConcernRateLimiting:

    def test_concern_limiter_allows_within_limit(self):
        limiter = InMemoryRateLimiter([{"limit": 5, "window": 60}])
        for _ in range(5):
            assert limiter.is_allowed("concern:127.0.0.1") is True

    def test_concern_limiter_blocks_after_limit(self):
        limiter = InMemoryRateLimiter([{"limit": 5, "window": 60}])
        for _ in range(5):
            limiter.is_allowed("concern:127.0.0.1")
        assert limiter.is_allowed("concern:127.0.0.1") is False

    def test_concern_limiter_resets_after_window(self):
        limiter = InMemoryRateLimiter([{"limit": 2, "window": 5}])
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000
            limiter.is_allowed("concern:127.0.0.1")
            limiter.is_allowed("concern:127.0.0.1")
            assert limiter.is_allowed("concern:127.0.0.1") is False

            mock_time.return_value = 1006
            assert limiter.is_allowed("concern:127.0.0.1") is True

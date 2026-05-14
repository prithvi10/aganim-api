"""
Unit tests for the Beta Self-Service Enrollment Flow.

Covers:
- Public signup API (GET /api/beta/signup/{token}, POST /api/beta/signup/{token})
- Token generation on invite (superadmin /beta/invite)
- Webhook auto-upgrade for accepted beta enrollments
- Email template with signup URL
"""
import pytest
import jwt
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ecommerce.api.main import app
from src.shared.db.database import Base, get_db
from src.ecommerce.db.models import (
    Shop, User, Plan, BetaEnrollment, UsageEventLog, OutreachLog,
)
from src.ecommerce.api.superadmin.auth import (
    ADMIN_JWT_SECRET, JWT_ALGORITHM,
)

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine():
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    del app.dependency_overrides[get_db]


def _make_token(expired: bool = False) -> str:
    exp = datetime.now(timezone.utc) + (
        timedelta(hours=-1) if expired else timedelta(hours=24)
    )
    payload = {
        "sub": "admin",
        "iat": datetime.now(timezone.utc),
        "exp": exp,
    }
    return jwt.encode(payload, ADMIN_JWT_SECRET, algorithm=JWT_ALGORITHM)


def _auth_header() -> dict:
    return {"Authorization": f"Bearer {_make_token()}"}


def _seed_shop(db_session, domain="beta-store.myshopify.com", plan_name="Free"):
    shop = Shop(
        domain=domain,
        access_token="tok_test",
        current_plan_name=plan_name,
        is_active=True,
        monthly_rewrites_used=0,
        lifetime_rewrites_remaining=10,
        monthly_missions_used=0,
        lifetime_missions_remaining=3,
        monthly_image_generations_used=0,
        lifetime_image_credits_remaining=5,
        monthly_cost_accumulated=0,
    )
    db_session.add(shop)
    db_session.commit()
    return shop


def _seed_enrollment(db_session, domain="beta-store.myshopify.com", status="invited", token=None):
    enrollment = BetaEnrollment(
        shop_domain=domain,
        status=status,
        invite_token=token or uuid.uuid4().hex,
        invited_at=datetime.now(timezone.utc),
        source="admin_invite",
    )
    db_session.add(enrollment)
    db_session.commit()
    return enrollment


# ===========================================================================
# Public Signup API — GET /api/beta/signup/{token}
# ===========================================================================

class TestPublicSignupValidation:
    """Tests for GET /api/beta/signup/{token} — token validation."""

    def test_valid_token_returns_200(self, client, db_session):
        enrollment = _seed_enrollment(db_session, token="valid-test-token-123")
        resp = client.get("/api/beta/signup/valid-test-token-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["status"] == "invited"
        assert data["shop_domain"] == "beta-store.myshopify.com"

    def test_invalid_token_returns_404(self, client):
        resp = client.get("/api/beta/signup/nonexistent-token")
        assert resp.status_code == 404
        assert "Invalid or expired" in resp.json()["detail"]

    def test_used_token_returns_410(self, client, db_session):
        _seed_enrollment(db_session, token="used-token", status="active")
        resp = client.get("/api/beta/signup/used-token")
        assert resp.status_code == 410
        assert "already been used" in resp.json()["detail"]

    def test_accepted_token_still_valid(self, client, db_session):
        _seed_enrollment(db_session, token="accepted-token", status="accepted")
        resp = client.get("/api/beta/signup/accepted-token")
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_completed_token_returns_410(self, client, db_session):
        _seed_enrollment(db_session, token="completed-token", status="completed")
        resp = client.get("/api/beta/signup/completed-token")
        assert resp.status_code == 410

    def test_churned_token_returns_410(self, client, db_session):
        _seed_enrollment(db_session, token="churned-token", status="churned")
        resp = client.get("/api/beta/signup/churned-token")
        assert resp.status_code == 410


# ===========================================================================
# Public Signup API — POST /api/beta/signup/{token}
# ===========================================================================

class TestPublicSignupSubmission:
    """Tests for POST /api/beta/signup/{token} — form submission."""

    def test_successful_signup_no_existing_shop(self, client, db_session):
        enrollment = _seed_enrollment(db_session, domain="new-store.myshopify.com", token="signup-token-1")
        resp = client.post("/api/beta/signup/signup-token-1", json={
            "store_name": "My New Store",
            "contact_email": "merchant@example.com",
            "shop_domain": "new-store.myshopify.com",
            "product_category": "fashion",
            "target_markets": "us",
            "purpose": "Translate product pages to English",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "accepted"
        assert "install_url" in data

        db_session.refresh(enrollment)
        assert enrollment.status == "accepted"
        assert enrollment.store_name == "My New Store"
        assert enrollment.contact_email == "merchant@example.com"
        assert enrollment.product_category == "fashion"
        assert enrollment.target_markets == "us"
        assert enrollment.purpose == "Translate product pages to English"
        assert enrollment.accepted_at is not None

    def test_successful_signup_existing_shop_activates_pro(self, client, db_session):
        shop = _seed_shop(db_session, domain="existing-beta.myshopify.com")
        enrollment = _seed_enrollment(
            db_session, domain="existing-beta.myshopify.com", token="signup-token-2"
        )

        resp = client.post("/api/beta/signup/signup-token-2", json={
            "store_name": "Existing Store",
            "contact_email": "owner@existing.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "active"

        db_session.refresh(shop)
        assert shop.is_beta_tester is True
        assert shop.current_plan_name == "Pro"
        assert shop.access_expires_at is not None
        assert shop.pending_plan_name == "Free"
        assert shop.monthly_rewrites_used == 0

        db_session.refresh(enrollment)
        assert enrollment.status == "active"
        assert enrollment.activated_at is not None

    def test_signup_with_invalid_token(self, client):
        resp = client.post("/api/beta/signup/fake-token", json={
            "store_name": "Test",
            "contact_email": "test@test.com",
        })
        assert resp.status_code == 404

    def test_signup_already_used_token(self, client, db_session):
        _seed_enrollment(db_session, token="already-used", status="active")
        resp = client.post("/api/beta/signup/already-used", json={
            "store_name": "Test",
            "contact_email": "test@test.com",
        })
        assert resp.status_code == 410

    def test_signup_updates_shop_domain_from_form(self, client, db_session):
        enrollment = _seed_enrollment(
            db_session, domain="placeholder.myshopify.com", token="domain-update-token"
        )
        resp = client.post("/api/beta/signup/domain-update-token", json={
            "store_name": "Real Store",
            "contact_email": "real@store.com",
            "shop_domain": "actual-store",
        })
        assert resp.status_code == 200
        db_session.refresh(enrollment)
        assert enrollment.shop_domain == "actual-store.myshopify.com"

    def test_signup_preserves_full_domain(self, client, db_session):
        _seed_enrollment(
            db_session, domain="whatever.myshopify.com", token="full-domain-token"
        )
        resp = client.post("/api/beta/signup/full-domain-token", json={
            "store_name": "Store",
            "contact_email": "a@b.com",
            "shop_domain": "my-real-store.myshopify.com",
        })
        assert resp.status_code == 200

    def test_signup_missing_required_fields(self, client, db_session):
        _seed_enrollment(db_session, domain="missing-fields.myshopify.com", token="missing-token")
        resp = client.post("/api/beta/signup/missing-token", json={
            "store_name": "Test",
        })
        assert resp.status_code == 422

    def test_signup_returns_install_url(self, client, db_session):
        _seed_enrollment(db_session, domain="url-check.myshopify.com", token="url-token")
        resp = client.post("/api/beta/signup/url-token", json={
            "store_name": "URL Store",
            "contact_email": "url@store.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "install_url" in data
        assert "shopify" in data["install_url"].lower() or "admin" in data["install_url"].lower()


# ===========================================================================
# Superadmin Invite — Token Generation
# ===========================================================================

class TestInviteTokenGeneration:
    """Tests for POST /beta/invite generating tokens and enrollment records."""

    @patch("src.ecommerce.api.superadmin.beta.send_email", new_callable=AsyncMock)
    def test_invite_creates_enrollment_with_token(self, mock_email, client, db_session):
        shop = _seed_shop(db_session, domain="invite-test.myshopify.com")
        user = User(username="invite-test.myshopify.com", email="shop@test.com")
        db_session.add(user)
        db_session.commit()

        resp = client.post(
            "/api/superadmin/beta/invite",
            json={"shop_domains": ["invite-test.myshopify.com"], "raw_emails": []},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] == 1
        assert "signup_url" in data["details"][0]
        assert "/beta/signup?token=" in data["details"][0]["signup_url"]

        enrollment = db_session.query(BetaEnrollment).filter(
            BetaEnrollment.shop_domain == "invite-test.myshopify.com"
        ).first()
        assert enrollment is not None
        assert enrollment.status == "invited"
        assert enrollment.invite_token is not None
        assert len(enrollment.invite_token) == 32

    @patch("src.ecommerce.api.superadmin.beta.send_email", new_callable=AsyncMock)
    def test_invite_raw_email_creates_enrollment(self, mock_email, client, db_session):
        resp = client.post(
            "/api/superadmin/beta/invite",
            json={"shop_domains": [], "raw_emails": ["merchant@gmail.com"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] == 1
        assert "signup_url" in data["details"][0]

        enrollment = db_session.query(BetaEnrollment).filter(
            BetaEnrollment.contact_email == "merchant@gmail.com"
        ).first()
        assert enrollment is not None
        assert enrollment.status == "invited"
        assert enrollment.invite_token is not None

    @patch("src.ecommerce.api.superadmin.beta.send_email", new_callable=AsyncMock)
    def test_invite_reuses_existing_enrollment_token(self, mock_email, client, db_session):
        shop = _seed_shop(db_session, domain="reuse-token.myshopify.com")
        user = User(username="reuse-token.myshopify.com", email="reuse@test.com")
        db_session.add(user)
        existing = _seed_enrollment(
            db_session, domain="reuse-token.myshopify.com", token="existing-token-abc"
        )
        db_session.commit()

        resp = client.post(
            "/api/superadmin/beta/invite",
            json={"shop_domains": ["reuse-token.myshopify.com"], "raw_emails": []},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "existing-token-abc" in data["details"][0]["signup_url"]

    @patch("src.ecommerce.api.superadmin.beta.send_email", new_callable=AsyncMock)
    def test_invite_passes_signup_url_to_email_template(self, mock_email, client, db_session):
        shop = _seed_shop(db_session, domain="email-url.myshopify.com")
        user = User(username="email-url.myshopify.com", email="emailurl@test.com")
        db_session.add(user)
        db_session.commit()

        resp = client.post(
            "/api/superadmin/beta/invite",
            json={"shop_domains": ["email-url.myshopify.com"], "raw_emails": []},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args
        html_body = call_kwargs.kwargs.get("html_body") or call_kwargs[1].get("html_body", "")
        assert "/beta/signup?token=" in html_body


# ===========================================================================
# Webhook Auto-Upgrade
# ===========================================================================

class TestWebhookAutoUpgrade:
    """Tests for app_installed webhook auto-detecting beta enrollments."""

    @patch("src.ecommerce.api.shopify.webhooks.verify_webhook_signature", new_callable=AsyncMock)
    def test_install_with_accepted_enrollment_upgrades_to_pro(self, mock_verify, client, db_session):
        enrollment = BetaEnrollment(
            shop_domain="webhook-test.myshopify.com",
            status="accepted",
            invite_token="webhook-token-1",
            invited_at=datetime.now(timezone.utc),
            accepted_at=datetime.now(timezone.utc),
            store_name="Webhook Store",
            contact_email="webhook@test.com",
            source="admin_invite",
        )
        db_session.add(enrollment)
        free_plan = db_session.query(Plan).filter(Plan.name == "Free").first()
        if not free_plan:
            free_plan = Plan(name="Free", price_usd_monthly=0)
            db_session.add(free_plan)
        db_session.commit()

        resp = client.post(
            "/webhooks/app/install",
            json={"myshopify_domain": "webhook-test.myshopify.com"},
            headers={"X-Shopify-Shop-Domain": "webhook-test.myshopify.com"},
        )
        assert resp.status_code == 200

        shop = db_session.query(Shop).filter(Shop.domain == "webhook-test.myshopify.com").first()
        assert shop is not None
        assert shop.is_beta_tester is True
        assert shop.current_plan_name == "Pro"
        assert shop.access_expires_at is not None
        assert shop.pending_plan_name == "Free"

        db_session.refresh(enrollment)
        assert enrollment.status == "active"
        assert enrollment.activated_at is not None

    @patch("src.ecommerce.api.shopify.webhooks.verify_webhook_signature", new_callable=AsyncMock)
    def test_install_without_enrollment_stays_free(self, mock_verify, client, db_session):
        free_plan = db_session.query(Plan).filter(Plan.name == "Free").first()
        if not free_plan:
            free_plan = Plan(name="Free", price_usd_monthly=0)
            db_session.add(free_plan)
            db_session.commit()

        resp = client.post(
            "/webhooks/app/install",
            json={"myshopify_domain": "normal-install.myshopify.com"},
            headers={"X-Shopify-Shop-Domain": "normal-install.myshopify.com"},
        )
        assert resp.status_code == 200

        shop = db_session.query(Shop).filter(Shop.domain == "normal-install.myshopify.com").first()
        assert shop is not None
        assert shop.is_beta_tester is False
        assert shop.current_plan_name != "Pro"

    @patch("src.ecommerce.api.shopify.webhooks.verify_webhook_signature", new_callable=AsyncMock)
    def test_install_with_invited_enrollment_does_not_upgrade(self, mock_verify, client, db_session):
        enrollment = BetaEnrollment(
            shop_domain="not-accepted.myshopify.com",
            status="invited",
            invite_token="still-invited-token",
            invited_at=datetime.now(timezone.utc),
            source="admin_invite",
        )
        db_session.add(enrollment)
        free_plan = db_session.query(Plan).filter(Plan.name == "Free").first()
        if not free_plan:
            free_plan = Plan(name="Free", price_usd_monthly=0)
            db_session.add(free_plan)
        db_session.commit()

        resp = client.post(
            "/webhooks/app/install",
            json={"myshopify_domain": "not-accepted.myshopify.com"},
            headers={"X-Shopify-Shop-Domain": "not-accepted.myshopify.com"},
        )
        assert resp.status_code == 200

        shop = db_session.query(Shop).filter(Shop.domain == "not-accepted.myshopify.com").first()
        assert shop is not None
        assert shop.is_beta_tester is False


# ===========================================================================
# Email Template — Signup URL
# ===========================================================================

class TestBetaInviteEmailTemplate:
    """Tests for beta_invite_email template with signup URL."""

    def test_template_includes_signup_url(self):
        from src.ecommerce.services.email_templates import beta_invite_email
        subject, html, text = beta_invite_email("Test Merchant", signup_url="https://example.com/beta/signup?token=abc123")
        assert "https://example.com/beta/signup?token=abc123" in html
        assert "https://example.com/beta/signup?token=abc123" in text
        assert "Sign Up for Beta" in html

    def test_template_without_signup_url_uses_install_link(self):
        from src.ecommerce.services.email_templates import beta_invite_email
        subject, html, text = beta_invite_email("Test Merchant")
        assert "Join the Beta" in html
        assert "shopify" in html.lower() or "admin.shopify" in html.lower()

    def test_template_mentions_6_weeks(self):
        from src.ecommerce.services.email_templates import beta_invite_email
        subject, html, text = beta_invite_email("Store", signup_url="https://x.com/signup?token=t")
        assert "6 weeks" in html or "6 weeks" in text


# ===========================================================================
# Public API — No Auth Required
# ===========================================================================

class TestPublicAPINoAuth:
    """Verifies public beta signup endpoints don't require authentication."""

    def test_get_signup_no_auth_header(self, client, db_session):
        enrollment = _seed_enrollment(db_session, domain="noauth.myshopify.com", token="noauth-token")
        resp = client.get("/api/beta/signup/noauth-token")
        assert resp.status_code == 200

    def test_post_signup_no_auth_header(self, client, db_session):
        _seed_enrollment(db_session, domain="noauth-post.myshopify.com", token="noauth-post-token")
        resp = client.post("/api/beta/signup/noauth-post-token", json={
            "store_name": "No Auth Store",
            "contact_email": "noauth@test.com",
        })
        assert resp.status_code == 200


# ===========================================================================
# Merchant Detail — New Fields in Response
# ===========================================================================

class TestMerchantDetailNewFields:
    """Tests that merchant detail/list includes invite_token and signup_url."""

    def test_merchant_detail_includes_signup_url(self, client, db_session):
        shop = _seed_shop(db_session, domain="detail-fields.myshopify.com")
        enrollment = BetaEnrollment(
            shop_domain="detail-fields.myshopify.com",
            status="active",
            invite_token="detail-token-xyz",
            invited_at=datetime.now(timezone.utc),
            activated_at=datetime.now(timezone.utc),
            store_name="Detail Store",
            contact_email="detail@store.com",
            purpose="Testing the beta",
            product_category="fashion",
            target_markets="eu",
            source="admin_invite",
        )
        db_session.add(enrollment)
        db_session.commit()

        resp = client.get(
            "/api/superadmin/beta/merchants/detail-fields.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        enrollment_data = data["enrollment"]
        assert enrollment_data["invite_token"] == "detail-token-xyz"
        assert "detail-token-xyz" in enrollment_data["signup_url"]
        assert enrollment_data["store_name"] == "Detail Store"
        assert enrollment_data["contact_email"] == "detail@store.com"
        assert enrollment_data["purpose"] == "Testing the beta"
        assert enrollment_data["product_category"] == "fashion"
        assert enrollment_data["target_markets"] == "eu"

    def test_merchant_list_includes_signup_url(self, client, db_session):
        shop = _seed_shop(db_session, domain="list-url.myshopify.com")
        enrollment = BetaEnrollment(
            shop_domain="list-url.myshopify.com",
            status="invited",
            invite_token="list-token-abc",
            invited_at=datetime.now(timezone.utc),
            source="admin_invite",
        )
        db_session.add(enrollment)
        db_session.commit()

        resp = client.get(
            "/api/superadmin/beta/merchants",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        merchants = data["merchants"]
        match = [m for m in merchants if m["shop_domain"] == "list-url.myshopify.com"]
        assert len(match) == 1
        assert "list-token-abc" in match[0]["signup_url"]

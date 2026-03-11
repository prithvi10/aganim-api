"""
Integration tests for the SES-backed outreach endpoints.

Covers end-to-end flows with a real in-memory DB and mocked SES:
- POST /outreach/send: success, partial failure, SES error
- POST /outreach/send-template: all four templates, missing shop, missing params
- History reflects real statuses after SES sends
- Full lifecycle: send template → verify history → send bulk → verify counts
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from src.ecommerce.api.main import app
from src.shared.db.database import Base, get_db
from src.ecommerce.db.models import Shop, OutreachLog
from src.ecommerce.api.superadmin.auth import (
    ADMIN_JWT_SECRET, JWT_ALGORITHM, ADMIN_USERNAME, ADMIN_PASSWORD,
)

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=pool.StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    del app.dependency_overrides[get_db]
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _get_token(client) -> str:
    resp = client.post("/api/superadmin/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _reset_tables():
    db = TestingSessionLocal()
    for model in [OutreachLog, Shop]:
        db.query(model).delete()
    db.commit()
    db.close()


def _seed_shop(domain="test-shop.myshopify.com", plan="Free"):
    db = TestingSessionLocal()
    shop = Shop(
        domain=domain,
        access_token="tok_test",
        current_plan_name=plan,
        is_active=True,
    )
    db.add(shop)
    db.commit()
    db.close()
    return shop


def _mock_ses_success(message_id="test-msg-001"):
    """Return a mock SES client that always succeeds."""
    client = MagicMock()
    client.send_email.return_value = {"MessageId": message_id}
    return client


def _mock_ses_failure(error_msg="SES Throttled"):
    """Return a mock SES client that always fails."""
    client = MagicMock()
    client.send_email.side_effect = Exception(error_msg)
    return client


# ===================================================================
# POST /outreach/send — with real DB, mocked SES
# ===================================================================

class TestSendOutreach:
    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_to_emails_success(self, mock_get_client, client):
        _reset_tables()
        mock_get_client.return_value = _mock_ses_success("ses-ok-1")
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["merchant@example.com"],
                "subject": "Welcome!",
                "body": "Check out our app.",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["recipients"] == 1
        assert data["sent"] == 1
        assert data["failed"] == 0
        assert data["details"][0]["status"] == "sent"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_to_merchant_domains(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("shop-a.myshopify.com", "Pro")
        _seed_shop("shop-b.myshopify.com", "Basic")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "merchant_domains": ["shop-a.myshopify.com", "shop-b.myshopify.com"],
                "subject": "Update",
                "body": "New features released.",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["recipients"] == 2
        assert resp.json()["sent"] == 2

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_mixed_emails_and_domains(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("mixed-shop.myshopify.com")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["ext@partner.com"],
                "merchant_domains": ["mixed-shop.myshopify.com"],
                "subject": "Promo",
                "body": "Special offer",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["recipients"] == 2
        assert resp.json()["sent"] == 2

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_partial_failure(self, mock_get_client, client):
        _reset_tables()
        ses = MagicMock()
        ses.send_email.side_effect = [
            {"MessageId": "ok-1"},
            Exception("Bounce"),
        ]
        mock_get_client.return_value = ses
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["good@test.com", "bad@bounce.com"],
                "subject": "Test",
                "body": "Partial test",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] == 1
        assert data["failed"] == 1
        assert data["details"][0]["status"] == "sent"
        assert data["details"][1]["status"] == "failed"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_all_fail(self, mock_get_client, client):
        _reset_tables()
        mock_get_client.return_value = _mock_ses_failure("Throttled")
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["a@b.com", "c@d.com"],
                "subject": "Fail",
                "body": "Should fail",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] == 0
        assert data["failed"] == 2

    def test_send_no_recipients_returns_400(self, client):
        token = _get_token(client)
        resp = client.post(
            "/api/superadmin/outreach/send",
            json={"to_emails": [], "merchant_domains": [], "subject": "X", "body": "X"},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_logs_persisted_to_db(self, mock_get_client, client):
        _reset_tables()
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["logged@test.com"],
                "subject": "Log Test",
                "body": "Check history",
            },
            headers=_auth(token),
        )

        resp = client.get("/api/superadmin/outreach/history", headers=_auth(token))
        assert resp.status_code == 200
        history = resp.json()["history"]
        match = [h for h in history if h["recipient_email"] == "logged@test.com"]
        assert len(match) == 1
        assert match[0]["status"] == "sent"
        assert match[0]["subject"] == "Log Test"


# ===================================================================
# POST /outreach/send-template
# ===================================================================

class TestSendTemplateOutreach:
    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_welcome_template(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("welcome-shop.myshopify.com", "Free")
        mock_get_client.return_value = _mock_ses_success("welcome-msg")
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "welcome",
                "merchant_domain": "welcome-shop.myshopify.com",
                "extra_params": {
                    "merchant_name": "Welcome Store",
                    "app_url": "https://app.crossborderagent.com",
                },
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "sent"
        assert data["template"] == "welcome"
        assert data["message_id"] == "welcome-msg"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_upgrade_template(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("upgrade-shop.myshopify.com", "Pro")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "upgrade",
                "merchant_domain": "upgrade-shop.myshopify.com",
                "extra_params": {
                    "merchant_name": "Upgrade Store",
                    "plan_name": "Pro",
                    "app_url": "https://app.crossborderagent.com",
                },
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"
        assert resp.json()["template"] == "upgrade"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_credit_limit_template(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("limit-shop.myshopify.com", "Basic")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "credit_limit",
                "merchant_domain": "limit-shop.myshopify.com",
                "extra_params": {
                    "plan_name": "Basic",
                    "upgrade_url": "https://app.crossborderagent.com/upgrade",
                },
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"
        assert resp.json()["template"] == "credit_limit"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_enterprise_template(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("enterprise-shop.myshopify.com", "Pro")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "enterprise",
                "merchant_domain": "enterprise-shop.myshopify.com",
                "extra_params": {"merchant_name": "Big Corp"},
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"
        assert resp.json()["template"] == "enterprise"

    def test_send_template_unknown_shop_returns_404(self, client):
        token = _get_token(client)
        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "welcome",
                "merchant_domain": "ghost.myshopify.com",
                "extra_params": {"app_url": "https://example.com"},
            },
            headers=_auth(token),
        )
        assert resp.status_code == 404

    def test_send_template_invalid_template_name(self, client):
        token = _get_token(client)
        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "nonexistent",
                "merchant_domain": "x.myshopify.com",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 422

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_template_ses_failure_logged(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("fail-shop.myshopify.com", "Free")
        mock_get_client.return_value = _mock_ses_failure("SES down")
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "welcome",
                "merchant_domain": "fail-shop.myshopify.com",
                "extra_params": {"app_url": "https://example.com"},
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert "error" in data

        hist = client.get("/api/superadmin/outreach/history", headers=_auth(token))
        logs = hist.json()["history"]
        fail_log = [l for l in logs if l["recipient_email"] == "fail-shop.myshopify.com"]
        assert len(fail_log) >= 1
        assert fail_log[0]["status"] == "failed"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_template_uses_custom_email(self, mock_get_client, client):
        """When extra_params includes 'email', use that instead of shop domain."""
        _reset_tables()
        _seed_shop("custom-email-shop.myshopify.com", "Free")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "welcome",
                "merchant_domain": "custom-email-shop.myshopify.com",
                "extra_params": {
                    "email": "owner@customdomain.com",
                    "app_url": "https://app.crossborderagent.com",
                },
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["recipient"] == "owner@customdomain.com"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_template_defaults_plan_from_shop(self, mock_get_client, client):
        """When plan_name not in extra_params, falls back to shop.current_plan_name."""
        _reset_tables()
        _seed_shop("default-plan-shop.myshopify.com", "Standard")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "credit_limit",
                "merchant_domain": "default-plan-shop.myshopify.com",
                "extra_params": {
                    "upgrade_url": "https://upgrade.example.com",
                },
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"


# ===================================================================
# Full lifecycle
# ===================================================================

class TestOutreachLifecycleSES:
    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_full_send_and_verify_history(self, mock_get_client, client):
        """Send template + bulk → verify all entries in history."""
        _reset_tables()
        _seed_shop("lifecycle-shop.myshopify.com", "Pro")
        mock_get_client.return_value = _mock_ses_success("lc-msg")
        token = _get_token(client)

        # 1. Send a template email
        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "upgrade",
                "merchant_domain": "lifecycle-shop.myshopify.com",
                "extra_params": {
                    "plan_name": "Pro",
                    "app_url": "https://app.crossborderagent.com",
                },
            },
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"

        # 2. Send a bulk free-form email
        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["a@test.com", "b@test.com"],
                "subject": "Promo",
                "body": "50% off for 24 hours!",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["sent"] == 2

        # 3. Verify history has all 3 entries
        resp = client.get("/api/superadmin/outreach/history", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        statuses = {h["status"] for h in data["history"]}
        assert statuses == {"sent"}

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_history_pagination(self, mock_get_client, client):
        _reset_tables()
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        for i in range(30):
            client.post(
                "/api/superadmin/outreach/send",
                json={
                    "to_emails": [f"user{i}@test.com"],
                    "subject": f"Email #{i}",
                    "body": "bulk",
                },
                headers=_auth(token),
            )

        page1 = client.get(
            "/api/superadmin/outreach/history?page=1&page_size=10",
            headers=_auth(token),
        )
        assert page1.status_code == 200
        assert len(page1.json()["history"]) == 10
        assert page1.json()["total"] == 30

        page2 = client.get(
            "/api/superadmin/outreach/history?page=2&page_size=10",
            headers=_auth(token),
        )
        assert page2.status_code == 200
        assert len(page2.json()["history"]) == 10

    def test_send_requires_auth(self, client):
        resp = client.post(
            "/api/superadmin/outreach/send",
            json={"to_emails": ["x@y.com"], "subject": "s", "body": "b"},
        )
        assert resp.status_code == 422

    def test_send_template_requires_auth(self, client):
        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "welcome",
                "merchant_domain": "x.myshopify.com",
            },
        )
        assert resp.status_code == 422

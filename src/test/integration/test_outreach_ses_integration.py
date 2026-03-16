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
from src.ecommerce.db.models import Shop, OutreachLog, User, Plan
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
    for model in [OutreachLog, User, Shop]:
        db.query(model).delete()
    db.commit()
    db.close()


def _seed_shop(domain="test-shop.myshopify.com", plan="Free", email=None):
    """Seed a Shop and optionally a User with an email address."""
    db = TestingSessionLocal()
    shop = Shop(
        domain=domain,
        access_token="tok_test",
        current_plan_name=plan,
        is_active=True,
    )
    db.add(shop)
    db.flush()

    plan_obj = db.query(Plan).filter_by(name=plan).first()
    if not plan_obj:
        plan_obj = Plan(
            name=plan, monthly_rewrite_limit=10, product_limit=10,
            billing_cycle_type="monthly", max_request_rate=10,
        )
        db.add(plan_obj)
        db.flush()

    user = User(username=domain, email=email, plan_id=plan_obj.id)
    db.add(user)
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


# ===================================================================
# Admin email endpoints: send-custom, send-feedback, send-rating
# ===================================================================

class TestAdminEmailEndpoints:
    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_custom_email(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("custom-a.myshopify.com", "Pro")
        _seed_shop("custom-b.myshopify.com", "Free")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/emails/send-custom",
            json={
                "recipient_filter": "all_active",
                "subject": "Big Announcement",
                "html_body": "<h2>New Feature</h2><p>Check it out!</p>",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["sent"] == 2
        assert data["filter"] == "all_active"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_custom_pro_only(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("pro-only.myshopify.com", "Pro")
        _seed_shop("free-user.myshopify.com", "Free")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/emails/send-custom",
            json={
                "recipient_filter": "pro_only",
                "subject": "Pro Exclusive",
                "html_body": "<p>VIP content</p>",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["filter"] == "pro_only"

    def test_send_custom_no_recipients(self, client):
        _reset_tables()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/emails/send-custom",
            json={
                "recipient_filter": "pro_only",
                "subject": "Test",
                "html_body": "<p>No one</p>",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 400
        assert "No recipients" in resp.json()["detail"]

    @patch("src.ecommerce.api.superadmin.outreach.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_feedback_email(self, mock_get_client, mock_sleep, client):
        _reset_tables()
        _seed_shop("fb-shop.myshopify.com", "Free")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/emails/send-feedback",
            json={
                "recipient_filter": "all_active",
                "feedback_link": "https://forms.example.com/feedback",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] == 1
        assert data["filter"] == "all_active"

    @patch("src.ecommerce.api.superadmin.outreach.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_rating_email(self, mock_get_client, mock_sleep, client):
        _reset_tables()
        _seed_shop("rate-shop.myshopify.com", "Pro")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/emails/send-rating",
            json={
                "recipient_filter": "all_active",
                "app_store_review_link": "https://apps.shopify.com/myapp#reviews",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["sent"] == 1

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_recipient_count_endpoint(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("cnt-a.myshopify.com", "Pro")
        _seed_shop("cnt-b.myshopify.com", "Pro")
        _seed_shop("cnt-c.myshopify.com", "Free")
        token = _get_token(client)

        resp = client.get(
            "/api/superadmin/outreach/recipients/count?recipient_filter=pro_only",
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["filter"] == "pro_only"
        assert data["count"] == 2

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_custom_logs_to_history(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("log-test.myshopify.com", "Free")
        mock_get_client.return_value = _mock_ses_success()
        token = _get_token(client)

        client.post(
            "/api/superadmin/outreach/emails/send-custom",
            json={
                "recipient_filter": "all_active",
                "subject": "Log Check",
                "html_body": "<p>Logged?</p>",
            },
            headers=_auth(token),
        )

        resp = client.get("/api/superadmin/outreach/history", headers=_auth(token))
        assert resp.status_code == 200
        history = resp.json()["history"]
        match = [h for h in history if h["subject"] == "Log Check"]
        assert len(match) >= 1
        assert match[0]["status"] == "sent"

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_custom_ses_failure(self, mock_get_client, client):
        _reset_tables()
        _seed_shop("fail-custom.myshopify.com", "Free")
        mock_get_client.return_value = _mock_ses_failure("SES down")
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/emails/send-custom",
            json={
                "recipient_filter": "all_active",
                "subject": "Fail Test",
                "html_body": "<p>fail</p>",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["failed"] == 1
        assert resp.json()["sent"] == 0

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_custom_uses_user_email(self, mock_get_client, client):
        """When User.email is populated, outreach should send to that address."""
        _reset_tables()
        _seed_shop("email-shop.myshopify.com", "Free", email="owner@realmail.com")
        ses = _mock_ses_success()
        mock_get_client.return_value = ses
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/emails/send-custom",
            json={
                "recipient_filter": "all_active",
                "subject": "User Email Test",
                "html_body": "<p>Hello</p>",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["sent"] == 1

        call_args = ses.send_email.call_args
        destination = call_args[1].get("Destination") or call_args[0][0] if call_args[0] else call_args[1]["Destination"]
        assert "owner@realmail.com" in destination["ToAddresses"]

    @patch("src.ecommerce.api.superadmin.outreach.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_feedback_uses_user_email(self, mock_get_client, mock_sleep, client):
        """Feedback emails should also go to User.email when available."""
        _reset_tables()
        _seed_shop("fb-email.myshopify.com", "Free", email="merchant@store.com")
        ses = _mock_ses_success()
        mock_get_client.return_value = ses
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/emails/send-feedback",
            json={
                "recipient_filter": "all_active",
                "feedback_link": "https://forms.example.com/feedback",
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["sent"] == 1

        call_args = ses.send_email.call_args
        destination = call_args[1].get("Destination") or call_args[0][0] if call_args[0] else call_args[1]["Destination"]
        assert "merchant@store.com" in destination["ToAddresses"]

    @patch("src.ecommerce.services.email_service._get_ses_client")
    def test_send_template_uses_user_email_as_fallback(self, mock_get_client, client):
        """send-template should use User.email when no explicit email param."""
        _reset_tables()
        _seed_shop("tmpl-email.myshopify.com", "Free", email="tmpl-owner@gmail.com")
        ses = _mock_ses_success()
        mock_get_client.return_value = ses
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send-template",
            json={
                "template": "welcome",
                "merchant_domain": "tmpl-email.myshopify.com",
                "extra_params": {
                    "merchant_name": "Template Shop",
                    "app_url": "https://app.crossborderagent.com",
                },
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.json()["recipient"] == "tmpl-owner@gmail.com"

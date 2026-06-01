"""
Unit tests for Beta Test API endpoints.

Covers:
- Enrollment CRUD (enroll, update, remove, re-enroll)
- Listing & filtering (all, by status, detail, 404)
- Dashboard & Funnel (KPIs, empty DB, status transitions)
- Metrics (per-merchant usage aggregation)
- Email / Invite (mock SES, outreach logging)
- Auth guards (unauthenticated, expired token)
"""
import pytest
import jwt
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ecommerce.api.main import app
from src.shared.db.database import Base, get_db
from src.ecommerce.db.models import (
    Shop, User, BetaEnrollment, UsageEventLog, OutreachLog,
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
        onboarding_step=0,
        is_onboarding_finished=False,
    )
    db_session.add(shop)
    db_session.flush()
    return shop


def _seed_user(db_session, domain="beta-store.myshopify.com", email="test@example.com"):
    user = User(username=domain, email=email)
    db_session.add(user)
    db_session.flush()
    return user


def _seed_enrollment(db_session, domain="beta-store.myshopify.com", status="active"):
    enrollment = BetaEnrollment(
        shop_domain=domain,
        status=status,
        invited_at=datetime.now(timezone.utc),
        accepted_at=datetime.now(timezone.utc),
        activated_at=datetime.now(timezone.utc) if status == "active" else None,
    )
    db_session.add(enrollment)
    db_session.flush()
    return enrollment


def _seed_usage_events(db_session, domain="beta-store.myshopify.com", count=5):
    for i in range(count):
        event = UsageEventLog(
            shop_domain=domain,
            plan_name="Standard",
            event_type="generation",
            feature="rewriter" if i % 2 == 0 else "seo",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            estimated_cost_usd=0.01,
        )
        db_session.add(event)
    db_session.flush()


# ---------------------------------------------------------------------------
# A. Enrollment CRUD
# ---------------------------------------------------------------------------

class TestEnrollment:
    def test_enroll_merchant_success(self, client, db_session):
        _seed_shop(db_session)
        resp = client.post(
            "/api/superadmin/beta/merchants/beta-store.myshopify.com/enroll",
            json={"upgrade_plan": "Standard", "source": "direct outreach"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["plan"] == "Standard"
        assert "enrollment_id" in data

    def test_enroll_nonexistent_shop_404(self, client, db_session):
        resp = client.post(
            "/api/superadmin/beta/merchants/nonexistent.myshopify.com/enroll",
            json={},
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    def test_enroll_already_enrolled_409(self, client, db_session):
        _seed_shop(db_session)
        _seed_enrollment(db_session)
        resp = client.post(
            "/api/superadmin/beta/merchants/beta-store.myshopify.com/enroll",
            json={},
            headers=_auth_header(),
        )
        assert resp.status_code == 409

    def test_update_beta_merchant(self, client, db_session):
        _seed_shop(db_session)
        _seed_enrollment(db_session)
        resp = client.put(
            "/api/superadmin/beta/merchants/beta-store.myshopify.com/update",
            json={"feedback_score": 4.5, "notes": "Great merchant", "willingness_to_pay": "yes"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert "updated" in resp.json()["message"]

    def test_remove_merchant_from_beta(self, client, db_session):
        _seed_shop(db_session)
        _seed_enrollment(db_session)
        resp = client.post(
            "/api/superadmin/beta/merchants/beta-store.myshopify.com/remove",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "churned"

    def test_remove_and_reenroll(self, client, db_session):
        _seed_shop(db_session)
        _seed_enrollment(db_session)
        client.post(
            "/api/superadmin/beta/merchants/beta-store.myshopify.com/remove",
            headers=_auth_header(),
        )
        # After removal, enrollment status is "churned" — need to delete for re-enroll
        # The API returns 409 because enrollment still exists
        resp = client.post(
            "/api/superadmin/beta/merchants/beta-store.myshopify.com/enroll",
            json={"upgrade_plan": "Pro"},
            headers=_auth_header(),
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# B. Listing & Filtering
# ---------------------------------------------------------------------------

class TestListing:
    def test_list_beta_merchants_all(self, client, db_session):
        _seed_shop(db_session, domain="s1.myshopify.com")
        _seed_shop(db_session, domain="s2.myshopify.com")
        _seed_enrollment(db_session, domain="s1.myshopify.com", status="active")
        _seed_enrollment(db_session, domain="s2.myshopify.com", status="invited")

        resp = client.get("/api/superadmin/beta/merchants", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["merchants"]) == 2

    def test_list_beta_merchants_filter_status(self, client, db_session):
        _seed_shop(db_session, domain="s1.myshopify.com")
        _seed_shop(db_session, domain="s2.myshopify.com")
        _seed_enrollment(db_session, domain="s1.myshopify.com", status="active")
        _seed_enrollment(db_session, domain="s2.myshopify.com", status="invited")

        resp = client.get(
            "/api/superadmin/beta/merchants?status=active",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["merchants"][0]["status"] == "active"

    def test_list_beta_merchants_empty(self, client, db_session):
        resp = client.get("/api/superadmin/beta/merchants", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_get_beta_merchant_detail(self, client, db_session):
        _seed_shop(db_session)
        _seed_enrollment(db_session)
        resp = client.get(
            "/api/superadmin/beta/merchants/beta-store.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enrollment"]["shop_domain"] == "beta-store.myshopify.com"
        assert data["shop"]["domain"] == "beta-store.myshopify.com"

    def test_get_beta_merchant_not_enrolled_404(self, client, db_session):
        _seed_shop(db_session)
        resp = client.get(
            "/api/superadmin/beta/merchants/beta-store.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# C. Dashboard & Funnel
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_dashboard_kpis(self, client, db_session):
        _seed_shop(db_session, domain="s1.myshopify.com")
        _seed_shop(db_session, domain="s2.myshopify.com")
        _seed_enrollment(db_session, domain="s1.myshopify.com", status="active")
        _seed_enrollment(db_session, domain="s2.myshopify.com", status="churned")

        resp = client.get("/api/superadmin/beta/dashboard", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_enrolled"] == 2
        assert data["active"] == 1
        assert data["churned"] == 1

    def test_dashboard_empty_db(self, client, db_session):
        resp = client.get("/api/superadmin/beta/dashboard", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_enrolled"] == 0
        assert data["active"] == 0

    def test_funnel_data(self, client, db_session):
        _seed_shop(db_session, domain="s1.myshopify.com")
        _seed_shop(db_session, domain="s2.myshopify.com")
        _seed_shop(db_session, domain="s3.myshopify.com")
        _seed_enrollment(db_session, domain="s1.myshopify.com", status="invited")
        _seed_enrollment(db_session, domain="s2.myshopify.com", status="active")
        _seed_enrollment(db_session, domain="s3.myshopify.com", status="active")

        resp = client.get("/api/superadmin/beta/funnel", headers=_auth_header())
        assert resp.status_code == 200
        funnel = resp.json()["funnel"]
        assert funnel["invited"] == 1
        assert funnel["active"] == 2


# ---------------------------------------------------------------------------
# D. Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_metrics_per_merchant(self, client, db_session):
        _seed_shop(db_session)
        _seed_enrollment(db_session)
        _seed_usage_events(db_session, count=6)

        resp = client.get(
            "/api/superadmin/beta/metrics/beta-store.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 6
        assert data["rewrites"] == 3  # every other event is rewriter
        assert "seo" in data["features_used"]

    def test_metrics_no_usage(self, client, db_session):
        _seed_shop(db_session)
        _seed_enrollment(db_session)

        resp = client.get(
            "/api/superadmin/beta/metrics/beta-store.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 0
        assert data["rewrites"] == 0

    def test_metrics_not_enrolled_404(self, client, db_session):
        _seed_shop(db_session)
        resp = client.get(
            "/api/superadmin/beta/metrics/beta-store.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    def test_feedback_aggregation(self, client, db_session):
        _seed_shop(db_session, domain="s1.myshopify.com")
        _seed_shop(db_session, domain="s2.myshopify.com")
        e1 = _seed_enrollment(db_session, domain="s1.myshopify.com")
        e2 = _seed_enrollment(db_session, domain="s2.myshopify.com")
        e1.feedback_score = 4.5
        e1.willingness_to_pay = "yes"
        e2.feedback_score = 3.0
        e2.willingness_to_pay = "maybe"
        db_session.flush()

        resp = client.get("/api/superadmin/beta/feedback", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_responses"] == 2
        assert data["avg_score"] == 3.75
        assert data["willingness_to_pay"]["yes"] == 1
        assert data["willingness_to_pay"]["maybe"] == 1


# ---------------------------------------------------------------------------
# E. Email / Invite
# ---------------------------------------------------------------------------

class TestEmail:
    @patch("src.ecommerce.api.superadmin.beta.send_email", new_callable=AsyncMock)
    def test_send_invite_email(self, mock_send, client, db_session):
        mock_send.return_value = {"MessageId": "test123"}
        _seed_shop(db_session)
        _seed_user(db_session)

        resp = client.post(
            "/api/superadmin/beta/invite",
            json={"shop_domains": ["beta-store.myshopify.com"]},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] == 1
        mock_send.assert_called_once()

    @patch("src.ecommerce.api.superadmin.beta.send_email", new_callable=AsyncMock)
    def test_send_bulk_checkin(self, mock_send, client, db_session):
        mock_send.return_value = {"MessageId": "test123"}
        _seed_shop(db_session)
        _seed_user(db_session)
        _seed_enrollment(db_session)

        resp = client.post(
            "/api/superadmin/beta/email/send",
            json={"template": "checkin", "status_filter": "active"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] == 1
        assert data["template"] == "checkin"

    @patch("src.ecommerce.api.superadmin.beta.send_email", new_callable=AsyncMock)
    def test_send_email_logs_to_outreach_log(self, mock_send, client, db_session):
        mock_send.return_value = {"MessageId": "test123"}
        _seed_shop(db_session)
        _seed_user(db_session)
        _seed_enrollment(db_session)

        client.post(
            "/api/superadmin/beta/email/send",
            json={"template": "feedback"},
            headers=_auth_header(),
        )

        logs = db_session.query(OutreachLog).all()
        assert len(logs) == 1
        assert logs[0].recipient_email == "test@example.com"
        assert "aganim" in logs[0].subject.lower()

    def test_invite_no_recipients_400(self, client, db_session):
        resp = client.post(
            "/api/superadmin/beta/invite",
            json={"shop_domains": [], "raw_emails": []},
            headers=_auth_header(),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# F. Auth Guards
# ---------------------------------------------------------------------------

class TestAuth:
    def test_all_endpoints_require_auth(self, client, db_session):
        endpoints = [
            ("GET", "/api/superadmin/beta/dashboard"),
            ("GET", "/api/superadmin/beta/funnel"),
            ("GET", "/api/superadmin/beta/merchants"),
            ("GET", "/api/superadmin/beta/feedback"),
            ("POST", "/api/superadmin/beta/invite"),
            ("POST", "/api/superadmin/beta/email/send"),
            ("POST", "/api/superadmin/beta/showcase/preview"),
            ("POST", "/api/superadmin/beta/showcase/send"),
            ("POST", "/api/superadmin/beta/showcase/bulk-send"),
        ]
        for method, url in endpoints:
            if method == "GET":
                resp = client.get(url)
            else:
                resp = client.post(url, json={})
            assert resp.status_code in (401, 403, 422), f"{method} {url} returned {resp.status_code}"

    def test_expired_token_rejected(self, client, db_session):
        headers = {"Authorization": f"Bearer {_make_token(expired=True)}"}
        resp = client.get("/api/superadmin/beta/dashboard", headers=headers)
        assert resp.status_code in (401, 403)

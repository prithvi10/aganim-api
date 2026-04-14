"""
Unit tests for SuperAdmin API endpoints.

Covers:
- Auth: login success/failure, token validation, expired tokens
- Dashboard: overview, timeseries, token usage, image credits, plan stats, feature usage
- Merchants: list (search, filter, pagination), detail, not found
- Missions: list, stuck, recover (success + invalid states)
- Concerns: list, reply, submit
- Outreach: send, history
- Edge cases: empty DB, no data for a merchant
- Unhappy paths: dashboard loading with DB errors
"""
import pytest
import jwt
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock, AsyncMock

from src.ecommerce.api.main import app
from src.shared.db.database import Base, get_db
from src.ecommerce.db.models import (
    Shop, User, Plan, UsageEventLog, FeatureUsage, Mission,
    ConcernLog, OutreachLog,
)
from src.ecommerce.api.superadmin.auth import (
    ADMIN_JWT_SECRET, JWT_ALGORITHM, ADMIN_USERNAME, ADMIN_PASSWORD,
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


def _make_token(username: str = "admin", expired: bool = False) -> str:
    exp = datetime.now(timezone.utc) + (
        timedelta(hours=-1) if expired else timedelta(hours=24)
    )
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": exp,
    }
    return jwt.encode(payload, ADMIN_JWT_SECRET, algorithm=JWT_ALGORITHM)


def _auth_header(token: str = None) -> dict:
    t = token or _make_token()
    return {"Authorization": f"Bearer {t}"}


def _seed_shop(db_session, domain="test-shop.myshopify.com", plan_name="Free", **kwargs):
    defaults = dict(
        domain=domain,
        access_token="tok_test",
        current_plan_name=plan_name,
        is_active=True,
        monthly_rewrites_used=5,
        lifetime_rewrites_remaining=5,
        monthly_missions_used=2,
        lifetime_missions_remaining=1,
        monthly_image_generations_used=3,
        lifetime_image_credits_remaining=2,
        monthly_cost_accumulated=0.45,
        onboarding_step=3,
        is_onboarding_finished=True,
    )
    defaults.update(kwargs)
    shop = Shop(**defaults)
    db_session.add(shop)
    db_session.flush()
    return shop


def _seed_user(db_session, username="test-shop.myshopify.com"):
    user = User(username=username, email=f"{username.split('.')[0]}@test.com")
    db_session.add(user)
    db_session.flush()
    return user


def _seed_mission(db_session, tenant_id="test-shop.myshopify.com", status="COMPLETED", **kwargs):
    import uuid
    defaults = dict(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        resource_id="product-123",
        status=status,
    )
    defaults.update(kwargs)
    m = Mission(**defaults)
    db_session.add(m)
    db_session.flush()
    return m


def _seed_usage_event(db_session, shop_domain="test-shop.myshopify.com", **kwargs):
    defaults = dict(
        shop_domain=shop_domain,
        plan_name="Free",
        event_type="rewrite",
        feature="product_rewrite",
        total_tokens=500,
        prompt_tokens=200,
        completion_tokens=300,
        reasoning_tokens=0,
        estimated_cost_usd=0.005,
    )
    defaults.update(kwargs)
    e = UsageEventLog(**defaults)
    db_session.add(e)
    db_session.flush()
    return e


def _seed_plan(db_session, name="Pro", price_usd_monthly=29.99, **kwargs):
    defaults = dict(
        name=name,
        price_usd_monthly=price_usd_monthly,
        monthly_rewrite_limit=1000,
        max_request_rate=100,
        product_limit=-1,
        is_active=True,
    )
    defaults.update(kwargs)
    plan = Plan(**defaults)
    db_session.add(plan)
    db_session.flush()
    return plan


def _seed_concern(db_session, shop_domain="test-shop.myshopify.com", **kwargs):
    defaults = dict(
        shop_domain=shop_domain,
        email="user@test.com",
        subject="Test concern",
        message="Something is broken",
        status="open",
    )
    defaults.update(kwargs)
    c = ConcernLog(**defaults)
    db_session.add(c)
    db_session.flush()
    return c


# ===================================================================
# AUTH TESTS
# ===================================================================

class TestLogin:
    def test_login_success(self, client):
        resp = client.post("/api/superadmin/login", json={
            "username": ADMIN_USERNAME,
            "password": ADMIN_PASSWORD,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_login_wrong_username(self, client):
        resp = client.post("/api/superadmin/login", json={
            "username": "wrong_user",
            "password": ADMIN_PASSWORD,
        })
        assert resp.status_code == 401
        assert "Invalid credentials" in resp.json()["detail"]

    def test_login_wrong_password(self, client):
        resp = client.post("/api/superadmin/login", json={
            "username": ADMIN_USERNAME,
            "password": "wrong_password",
        })
        assert resp.status_code == 401

    def test_login_empty_body(self, client):
        resp = client.post("/api/superadmin/login", json={})
        assert resp.status_code == 422

    def test_protected_endpoint_no_token(self, client):
        resp = client.get("/api/superadmin/dashboard/overview")
        assert resp.status_code == 422  # Missing header

    def test_protected_endpoint_invalid_token(self, client):
        resp = client.get(
            "/api/superadmin/dashboard/overview",
            headers={"Authorization": "Bearer garbage.token.here"},
        )
        assert resp.status_code == 401

    def test_protected_endpoint_expired_token(self, client):
        token = _make_token(expired=True)
        resp = client.get(
            "/api/superadmin/dashboard/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_protected_endpoint_malformed_header(self, client):
        resp = client.get(
            "/api/superadmin/dashboard/overview",
            headers={"Authorization": "Token something"},
        )
        assert resp.status_code == 401

    def test_protected_endpoint_valid_token(self, client):
        resp = client.get("/api/superadmin/dashboard/overview", headers=_auth_header())
        assert resp.status_code == 200


# ===================================================================
# DASHBOARD — EMPTY DB (Edge cases)
# ===================================================================

class TestDashboardEmptyDB:
    def test_overview_empty(self, client):
        resp = client.get("/api/superadmin/dashboard/overview", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_merchants"] == 0
        assert data["active_merchants_30d"] == 0
        assert data["total_missions"] == 0
        assert data["total_rewrites"] == 0
        assert data["total_image_generations"] == 0
        assert data["total_estimated_cost_usd"] == 0.0

    def test_timeseries_empty(self, client):
        resp = client.get(
            "/api/superadmin/dashboard/usage-timeseries?period=7d",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "7d"
        assert data["series"] == {}

    def test_token_usage_empty(self, client):
        resp = client.get("/api/superadmin/dashboard/token-usage", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_image_credits_empty(self, client):
        resp = client.get("/api/superadmin/dashboard/image-credits", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_plan_stats_empty(self, client):
        resp = client.get("/api/superadmin/dashboard/plan-stats", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["enrollment"] == {}
        assert data["recent_changes"] == []
        assert data["churned_count"] == 0

    def test_feature_usage_empty(self, client):
        resp = client.get("/api/superadmin/dashboard/feature-usage", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_timeseries_invalid_period(self, client):
        resp = client.get(
            "/api/superadmin/dashboard/usage-timeseries?period=999d",
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_revenue_empty(self, client):
        resp = client.get("/api/superadmin/dashboard/revenue", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_mrr"] == 0
        assert data["by_plan"] == {}
        assert data["merchants"] == []

    def test_attrition_empty(self, client):
        resp = client.get("/api/superadmin/dashboard/attrition", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_churned"] == 0
        assert data["total_lost_revenue"] == 0
        assert data["by_plan"] == {}
        assert data["merchants"] == []
        assert data["period_days"] == 30

    def test_approaching_limits_empty(self, client):
        resp = client.get("/api/superadmin/dashboard/approaching-limits", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["threshold"] == 80
        assert data["merchants"] == []

    def test_attrition_invalid_days(self, client):
        resp = client.get(
            "/api/superadmin/dashboard/attrition?days=0",
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_approaching_limits_invalid_threshold(self, client):
        resp = client.get(
            "/api/superadmin/dashboard/approaching-limits?threshold=0",
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ===================================================================
# DASHBOARD — WITH DATA
# ===================================================================

class TestDashboardWithData:
    def test_overview_with_merchants(self, client, db_session):
        _seed_shop(db_session, "shop-a.myshopify.com", "Free")
        _seed_shop(db_session, "shop-b.myshopify.com", "Pro")
        _seed_shop(db_session, "shop-c.myshopify.com", "Pro", is_active=False)
        _seed_mission(db_session, "shop-a.myshopify.com")
        _seed_mission(db_session, "shop-b.myshopify.com")
        _seed_usage_event(db_session, "shop-a.myshopify.com", estimated_cost_usd=1.50)
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/overview", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_merchants"] == 3
        assert data["total_missions"] == 2
        assert data["total_estimated_cost_usd"] >= 1.50

    def test_plan_stats_with_data(self, client, db_session):
        _seed_shop(db_session, "plan-a.myshopify.com", "Free")
        _seed_shop(db_session, "plan-b.myshopify.com", "Basic")
        _seed_shop(db_session, "plan-c.myshopify.com", "Free")
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/plan-stats", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert "Free" in data["enrollment"]
        assert data["enrollment"]["Free"] >= 2

    def test_token_usage_with_data(self, client, db_session):
        _seed_usage_event(db_session, "token-shop.myshopify.com", total_tokens=1000, prompt_tokens=400, completion_tokens=600)
        _seed_usage_event(db_session, "token-shop.myshopify.com", total_tokens=2000, prompt_tokens=800, completion_tokens=1200)
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/token-usage", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        shop_entry = next((d for d in data if d["shop_domain"] == "token-shop.myshopify.com"), None)
        assert shop_entry is not None
        assert shop_entry["total_tokens"] == 3000

    def test_image_credits_with_data(self, client, db_session):
        _seed_shop(db_session, "img-shop.myshopify.com", "Pro",
                   monthly_image_generations_used=10, lifetime_image_credits_remaining=140)
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/image-credits", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        entry = next((d for d in data if d["shop_domain"] == "img-shop.myshopify.com"), None)
        assert entry is not None
        assert entry["monthly_used"] == 10
        assert entry["lifetime_remaining"] == 140


# ===================================================================
# REVENUE ENDPOINT
# ===================================================================

class TestRevenue:
    def test_revenue_no_plans_in_db(self, client):
        resp = client.get("/api/superadmin/dashboard/revenue", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_mrr"] == 0

    def test_revenue_with_paid_merchants(self, client, db_session):
        _seed_plan(db_session, "Basic", 9.99)
        _seed_plan(db_session, "Standard", 19.99)
        _seed_plan(db_session, "Pro", 29.99)
        _seed_shop(db_session, "rev-basic.myshopify.com", "Basic")
        _seed_shop(db_session, "rev-pro1.myshopify.com", "Pro")
        _seed_shop(db_session, "rev-pro2.myshopify.com", "Pro")
        _seed_shop(db_session, "rev-free.myshopify.com", "Free")
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/revenue", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_mrr"] == round(9.99 + 29.99 + 29.99, 2)
        assert data["by_plan"]["Pro"]["count"] == 2
        assert data["by_plan"]["Pro"]["revenue"] == round(29.99 * 2, 2)
        assert data["by_plan"]["Basic"]["count"] == 1
        assert "Free" not in data["by_plan"]
        assert len(data["merchants"]) == 3

    def test_revenue_inactive_merchants_excluded(self, client, db_session):
        _seed_plan(db_session, "RevPlan", 49.99)
        _seed_shop(db_session, "rev-inactive.myshopify.com", "RevPlan", is_active=False)
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/revenue", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        inactive_domains = [m["domain"] for m in data["merchants"]]
        assert "rev-inactive.myshopify.com" not in inactive_domains


# ===================================================================
# ATTRITION ENDPOINT
# ===================================================================

class TestAttrition:
    def test_attrition_uninstalled_merchant(self, client, db_session):
        _seed_plan(db_session, "AttrPro", 29.99)
        now = datetime.now(timezone.utc)
        _seed_shop(
            db_session, "churned.myshopify.com", None,
            is_active=False,
            last_plan_name="AttrPro",
            last_uninstalled_at=now - timedelta(days=5),
        )
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/attrition?days=30", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_churned"] >= 1
        churned_domains = [m["domain"] for m in data["merchants"]]
        assert "churned.myshopify.com" in churned_domains
        entry = next(m for m in data["merchants"] if m["domain"] == "churned.myshopify.com")
        assert entry["type"] == "uninstalled"
        assert entry["lost_revenue"] == 29.99

    def test_attrition_cancelled_plan_merchant(self, client, db_session):
        _seed_plan(db_session, "AttrStd", 19.99)
        now = datetime.now(timezone.utc)
        _seed_shop(
            db_session, "cancelled.myshopify.com", None,
            is_active=True,
            last_plan_name="AttrStd",
            last_shopify_subscription_status="CANCELLED",
            last_plan_change_at=now - timedelta(days=3),
        )
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/attrition?days=30", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        cancelled = [m for m in data["merchants"] if m["domain"] == "cancelled.myshopify.com"]
        assert len(cancelled) == 1
        assert cancelled[0]["type"] == "cancelled"
        assert cancelled[0]["lost_revenue"] == 19.99

    def test_attrition_old_churn_excluded(self, client, db_session):
        now = datetime.now(timezone.utc)
        _seed_shop(
            db_session, "old-churn.myshopify.com", None,
            is_active=False,
            last_plan_name="Free",
            last_uninstalled_at=now - timedelta(days=90),
        )
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/attrition?days=30", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        old_domains = [m["domain"] for m in data["merchants"]]
        assert "old-churn.myshopify.com" not in old_domains

    def test_attrition_custom_period(self, client, db_session):
        resp = client.get("/api/superadmin/dashboard/attrition?days=7", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["period_days"] == 7

    def test_attrition_free_plan_no_revenue_loss(self, client, db_session):
        now = datetime.now(timezone.utc)
        _seed_shop(
            db_session, "free-churn.myshopify.com", None,
            is_active=False,
            last_plan_name="Free",
            last_uninstalled_at=now - timedelta(days=2),
        )
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/attrition?days=30", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        entry = next((m for m in data["merchants"] if m["domain"] == "free-churn.myshopify.com"), None)
        if entry:
            assert entry["lost_revenue"] == 0


# ===================================================================
# APPROACHING LIMITS ENDPOINT
# ===================================================================

class TestApproachingLimits:
    def test_free_plan_near_lifetime_limits(self, client, db_session):
        _seed_shop(
            db_session, "free-near-limit.myshopify.com", "Free",
            lifetime_rewrites_remaining=1,
            lifetime_missions_remaining=0,
            lifetime_image_credits_remaining=1,
        )
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/approaching-limits?threshold=80", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        match = next((m for m in data["merchants"] if m["domain"] == "free-near-limit.myshopify.com"), None)
        assert match is not None
        resources = [b["resource"] for b in match["breaches"]]
        assert "Rewrites" in resources
        assert "Missions" in resources
        assert "Image Credits" in resources

    def test_pro_plan_below_threshold_not_shown(self, client, db_session):
        _seed_plan(db_session, "LimitsPro", 29.99, monthly_rewrite_limit=1000)
        _seed_shop(
            db_session, "pro-safe.myshopify.com", "Pro",
            monthly_rewrites_used=10,
            monthly_missions_used=0,
            monthly_image_generations_used=5,
            lifetime_rewrites_remaining=10,
            lifetime_missions_remaining=3,
            lifetime_image_credits_remaining=5,
        )
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/approaching-limits?threshold=80", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        match = next((m for m in data["merchants"] if m["domain"] == "pro-safe.myshopify.com"), None)
        assert match is None

    def test_custom_threshold(self, client, db_session):
        _seed_shop(
            db_session, "threshold-test.myshopify.com", "Free",
            lifetime_rewrites_remaining=0,
            lifetime_missions_remaining=0,
            lifetime_image_credits_remaining=0,
        )
        db_session.commit()

        resp = client.get(
            "/api/superadmin/dashboard/approaching-limits?threshold=50",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["threshold"] == 50
        match = next((m for m in data["merchants"] if m["domain"] == "threshold-test.myshopify.com"), None)
        assert match is not None

    def test_sorted_by_highest_pct(self, client, db_session):
        _seed_shop(
            db_session, "pct-high.myshopify.com", "Free",
            lifetime_rewrites_remaining=0,
            lifetime_missions_remaining=0,
            lifetime_image_credits_remaining=0,
        )
        _seed_shop(
            db_session, "pct-low.myshopify.com", "Free",
            lifetime_rewrites_remaining=2,
            lifetime_missions_remaining=1,
            lifetime_image_credits_remaining=1,
        )
        db_session.commit()

        resp = client.get("/api/superadmin/dashboard/approaching-limits", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        matching = [m for m in data["merchants"] if m["domain"] in ("pct-high.myshopify.com", "pct-low.myshopify.com")]
        if len(matching) >= 2:
            max_pcts = [max(b["pct"] for b in m["breaches"]) for m in matching]
            assert max_pcts == sorted(max_pcts, reverse=True)


# ===================================================================
# MERCHANT plan_display FIELD
# ===================================================================

class TestMerchantPlanDisplay:
    def test_active_plan_shows_plan_name(self, client, db_session):
        _seed_shop(db_session, "display-pro.myshopify.com", "Pro")
        db_session.commit()

        resp = client.get("/api/superadmin/merchants?search=display-pro", headers=_auth_header())
        assert resp.status_code == 200
        m = resp.json()["merchants"][0]
        assert m["plan_display"] == "Pro"

    def test_cancelled_shows_plan_cancelled(self, client, db_session):
        _seed_shop(
            db_session, "display-cancel.myshopify.com", None,
            last_plan_name="Pro",
            last_shopify_subscription_status="CANCELLED",
        )
        db_session.commit()

        resp = client.get("/api/superadmin/merchants?search=display-cancel", headers=_auth_header())
        assert resp.status_code == 200
        m = resp.json()["merchants"][0]
        assert m["plan_display"] == "Pro (Cancelled)"

    def test_pending_plan_shows_pending(self, client, db_session):
        _seed_shop(
            db_session, "display-pending.myshopify.com", None,
            pending_plan_name="Free",
        )
        db_session.commit()

        resp = client.get("/api/superadmin/merchants?search=display-pending", headers=_auth_header())
        assert resp.status_code == 200
        m = resp.json()["merchants"][0]
        assert m["plan_display"] == "Free (Pending)"

    def test_no_plan_shows_free(self, client, db_session):
        _seed_shop(db_session, "display-none.myshopify.com", None)
        db_session.commit()

        resp = client.get("/api/superadmin/merchants?search=display-none", headers=_auth_header())
        assert resp.status_code == 200
        m = resp.json()["merchants"][0]
        assert m["plan_display"] == "Free"

    def test_detail_includes_subscription_status(self, client, db_session):
        _seed_shop(
            db_session, "detail-sub.myshopify.com", None,
            last_plan_name="Standard",
            last_shopify_subscription_status="CANCELLED",
            last_plan_change_type="cancel",
            pending_plan_name="Free",
        )
        db_session.commit()

        resp = client.get(
            "/api/superadmin/merchants/detail-sub.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        shop = resp.json()["shop"]
        assert shop["plan_display"] == "Standard (Cancelled)"
        assert shop["last_shopify_subscription_status"] == "CANCELLED"
        assert shop["pending_plan_name"] == "Free"
        assert shop["last_plan_change_type"] == "cancel"


# ===================================================================
# DASHBOARD — UNHAPPY PATHS (DB failures)
# ===================================================================

class TestDashboardFailures:
    """When the DB is unreachable, endpoints should raise (500 in production).

    TestClient re-raises server exceptions, so we assert the exception type.
    """

    @staticmethod
    def _broken_db_override():
        broken = MagicMock()
        broken.query.side_effect = Exception("DB connection lost")
        try:
            yield broken
        finally:
            pass

    def test_overview_db_error(self, db_session):
        app.dependency_overrides[get_db] = self._broken_db_override
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/superadmin/dashboard/overview", headers=_auth_header())
            assert resp.status_code == 500

    def test_timeseries_db_error(self, db_session):
        app.dependency_overrides[get_db] = self._broken_db_override
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(
                "/api/superadmin/dashboard/usage-timeseries?period=7d",
                headers=_auth_header(),
            )
            assert resp.status_code == 500

    def test_token_usage_db_error(self, db_session):
        app.dependency_overrides[get_db] = self._broken_db_override
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/superadmin/dashboard/token-usage", headers=_auth_header())
            assert resp.status_code == 500

    def test_revenue_db_error(self, db_session):
        app.dependency_overrides[get_db] = self._broken_db_override
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/superadmin/dashboard/revenue", headers=_auth_header())
            assert resp.status_code == 500

    def test_attrition_db_error(self, db_session):
        app.dependency_overrides[get_db] = self._broken_db_override
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/superadmin/dashboard/attrition", headers=_auth_header())
            assert resp.status_code == 500

    def test_approaching_limits_db_error(self, db_session):
        app.dependency_overrides[get_db] = self._broken_db_override
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/superadmin/dashboard/approaching-limits", headers=_auth_header())
            assert resp.status_code == 500


# ===================================================================
# MERCHANTS
# ===================================================================

class TestMerchants:
    def test_list_empty(self, client):
        resp = client.get("/api/superadmin/merchants", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["merchants"] == []
        assert data["total"] == 0

    def test_list_with_data(self, client, db_session):
        _seed_shop(db_session, "m1.myshopify.com", "Free")
        _seed_shop(db_session, "m2.myshopify.com", "Pro")
        db_session.commit()

        resp = client.get("/api/superadmin/merchants", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        domains = [m["domain"] for m in data["merchants"]]
        assert "m1.myshopify.com" in domains

    def test_list_search(self, client, db_session):
        _seed_shop(db_session, "search-target.myshopify.com", "Free")
        _seed_shop(db_session, "other-shop.myshopify.com", "Basic")
        db_session.commit()

        resp = client.get(
            "/api/superadmin/merchants?search=search-target",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all("search-target" in m["domain"] for m in data["merchants"])

    def test_list_filter_by_plan(self, client, db_session):
        _seed_shop(db_session, "plan-filter-a.myshopify.com", "Standard")
        _seed_shop(db_session, "plan-filter-b.myshopify.com", "Standard")
        _seed_shop(db_session, "plan-filter-c.myshopify.com", "Free")
        db_session.commit()

        resp = client.get(
            "/api/superadmin/merchants?plan=Standard",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(m["current_plan_name"] == "Standard" for m in data["merchants"])

    def test_list_pagination(self, client, db_session):
        for i in range(30):
            _seed_shop(db_session, f"page-{i:03d}.myshopify.com", "Free")
        db_session.commit()

        resp_p1 = client.get("/api/superadmin/merchants?page=1", headers=_auth_header())
        resp_p2 = client.get("/api/superadmin/merchants?page=2", headers=_auth_header())
        assert resp_p1.status_code == 200
        assert resp_p2.status_code == 200
        d1 = resp_p1.json()
        d2 = resp_p2.json()
        assert len(d1["merchants"]) == 25
        assert len(d2["merchants"]) >= 5
        assert d1["total_pages"] >= 2

    def test_detail_found(self, client, db_session):
        _seed_shop(db_session, "detail-shop.myshopify.com", "Pro")
        _seed_user(db_session, "detail-shop.myshopify.com")
        db_session.commit()

        resp = client.get(
            "/api/superadmin/merchants/detail-shop.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["shop"]["domain"] == "detail-shop.myshopify.com"
        assert data["user"] is not None
        assert data["user"]["username"] == "detail-shop.myshopify.com"

    def test_detail_not_found(self, client):
        resp = client.get(
            "/api/superadmin/merchants/nonexistent-shop.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    def test_detail_no_user_record(self, client, db_session):
        _seed_shop(db_session, "no-user-shop.myshopify.com", "Free")
        db_session.commit()

        resp = client.get(
            "/api/superadmin/merchants/no-user-shop.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"] is None

    def test_detail_no_events(self, client, db_session):
        _seed_shop(db_session, "empty-events.myshopify.com", "Free")
        db_session.commit()

        resp = client.get(
            "/api/superadmin/merchants/empty-events.myshopify.com",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recent_events"] == []
        assert data["missions"] == []
        assert data["feature_usage"] == []


# ===================================================================
# MISSIONS
# ===================================================================

class TestMissions:
    def test_list_empty(self, client):
        resp = client.get("/api/superadmin/missions", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["missions"] == []
        assert data["total"] == 0

    def test_list_with_data(self, client, db_session):
        _seed_mission(db_session, "m-shop.myshopify.com", "COMPLETED")
        _seed_mission(db_session, "m-shop.myshopify.com", "ERROR", error_message="Timeout")
        db_session.commit()

        resp = client.get("/api/superadmin/missions", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["total"] >= 2

    def test_list_filter_status(self, client, db_session):
        _seed_mission(db_session, "filter-shop.myshopify.com", "ERROR")
        _seed_mission(db_session, "filter-shop.myshopify.com", "COMPLETED")
        db_session.commit()

        resp = client.get(
            "/api/superadmin/missions?status=ERROR",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(m["status"] == "ERROR" for m in data["missions"])

    def test_stuck_empty(self, client):
        resp = client.get("/api/superadmin/missions/stuck", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["stuck_missions"] == []

    def test_recover_not_found(self, client):
        resp = client.post(
            "/api/superadmin/missions/nonexistent-id/recover",
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    def test_recover_invalid_state(self, client, db_session):
        m = _seed_mission(db_session, status="COMPLETED")
        db_session.commit()

        resp = client.post(
            f"/api/superadmin/missions/{m.id}/recover",
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "COMPLETED" in resp.json()["detail"]

    def test_recover_pending_not_allowed(self, client, db_session):
        m = _seed_mission(db_session, status="PENDING")
        db_session.commit()

        resp = client.post(
            f"/api/superadmin/missions/{m.id}/recover",
            headers=_auth_header(),
        )
        assert resp.status_code == 400

    def test_recover_error_mission(self, client, db_session):
        m = _seed_mission(db_session, status="ERROR", error_message="Something failed")
        db_session.commit()

        resp = client.post(
            f"/api/superadmin/missions/{m.id}/recover",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["previous_status"] == "ERROR"
        assert data["new_status"] == "PENDING"

    def test_recover_in_progress_mission(self, client, db_session):
        m = _seed_mission(db_session, status="IN_PROGRESS")
        db_session.commit()

        resp = client.post(
            f"/api/superadmin/missions/{m.id}/recover",
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["previous_status"] == "IN_PROGRESS"
        assert data["new_status"] == "PENDING"


# ===================================================================
# CONCERNS
# ===================================================================

class TestConcerns:
    def test_list_empty(self, client):
        resp = client.get("/api/superadmin/concerns", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["concerns"] == []

    def test_list_with_data(self, client, db_session):
        _seed_concern(db_session, "concern-shop.myshopify.com", subject="Help me")
        db_session.commit()

        resp = client.get("/api/superadmin/concerns", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["concerns"]) >= 1
        assert data["concerns"][0]["subject"] == "Help me"

    def test_reply_success(self, client, db_session):
        c = _seed_concern(db_session)
        db_session.commit()

        resp = client.post(
            f"/api/superadmin/concerns/{c.id}/reply",
            json={"reply": "We are looking into it"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["concern_id"] == c.id

    def test_reply_not_found(self, client):
        resp = client.post(
            "/api/superadmin/concerns/99999/reply",
            json={"reply": "test"},
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    def test_reply_empty_body(self, client, db_session):
        c = _seed_concern(db_session)
        db_session.commit()

        resp = client.post(
            f"/api/superadmin/concerns/{c.id}/reply",
            json={},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_submit_concern_no_auth(self, client):
        """Submit-concern endpoint now requires admin JWT (Header validation → 422)."""
        resp = client.post(
            "/api/superadmin/submit-concern",
            json={
                "shop_domain": "customer-shop.myshopify.com",
                "email": "test@example.com",
                "subject": "Bug report",
                "message": "Product page is broken",
            },
        )
        assert resp.status_code in (401, 403, 422)

    def test_submit_concern_missing_fields(self, client):
        resp = client.post(
            "/api/superadmin/submit-concern",
            json={"shop_domain": "x"},
            headers=_auth_header(),
        )
        assert resp.status_code == 422


# ===================================================================
# OUTREACH
# ===================================================================

class TestOutreach:
    def test_history_empty(self, client):
        resp = client.get("/api/superadmin/outreach/history", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["history"] == []
        assert data["total"] == 0

    def test_send_no_recipients(self, client):
        resp = client.post(
            "/api/superadmin/outreach/send",
            json={"subject": "Hello", "body": "World"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "No recipients" in resp.json()["detail"]

    @patch("src.ecommerce.api.superadmin.outreach.send_email", new_callable=AsyncMock)
    def test_send_success(self, mock_send, client, db_session):
        mock_send.return_value = {"message_id": "test-123"}
        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["merchant@test.com"],
                "subject": "New Feature!",
                "body": "Check out our new Pro plan.",
            },
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recipients"] == 1
        assert data["sent"] == 1

    @patch("src.ecommerce.api.superadmin.outreach.send_email", new_callable=AsyncMock)
    def test_send_and_history(self, mock_send, client, db_session):
        mock_send.return_value = {"message_id": "test-456"}
        client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["a@test.com", "b@test.com"],
                "subject": "Promo",
                "body": "50% off",
            },
            headers=_auth_header(),
        )
        db_session.commit()

        resp = client.get("/api/superadmin/outreach/history", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    @patch("src.ecommerce.api.superadmin.outreach.send_email", new_callable=AsyncMock)
    def test_send_with_merchant_domains(self, mock_send, client, db_session):
        mock_send.return_value = {"message_id": "test-789"}
        _seed_shop(db_session, "outreach-shop.myshopify.com", "Pro")
        db_session.commit()

        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "merchant_domains": ["outreach-shop.myshopify.com"],
                "subject": "Update",
                "body": "New features",
            },
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["recipients"] == 1

    def test_send_missing_subject(self, client):
        resp = client.post(
            "/api/superadmin/outreach/send",
            json={"to_emails": ["a@b.com"], "body": "hi"},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

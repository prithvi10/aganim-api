"""
Integration tests for SuperAdmin portal flows.

Tests end-to-end workflows that span multiple endpoints:
- Mission stuck detection → recovery → verification
- Concern lifecycle: merchant submit → admin list → reply → verify status
- Outreach lifecycle: compose → send → verify history
- Merchant monitoring: multi-shop setup → dashboard aggregation → drill-down
- Plan changes: upgrade/downgrade tracking in dashboard stats
- Auth lifecycle: login → use token → token expiry
"""
import pytest
import uuid
import jwt
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

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
    for model in [OutreachLog, ConcernLog, UsageEventLog, FeatureUsage, Mission, Shop, User, Plan]:
        db.query(model).delete()
    db.commit()
    db.close()


# ===================================================================
# Integration: Mission Stuck → Recovery → Verification
# ===================================================================

class TestMissionRecoveryFlow:
    """
    Scenario: A Pro merchant starts a mission that gets stuck in IN_PROGRESS.
    Admin detects it via stuck endpoint and recovers it. Verify it moves to PENDING.
    Then a second mission is in ERROR state and is also recovered.
    """

    def test_full_stuck_mission_recovery(self, client):
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        # Setup: create a shop and two missions
        shop = Shop(
            domain="stuck-test.myshopify.com",
            access_token="tok",
            current_plan_name="Pro",
            is_active=True,
        )
        db.add(shop)
        db.flush()

        stuck_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        mission_stuck = Mission(
            id=str(uuid.uuid4()),
            tenant_id="stuck-test.myshopify.com",
            resource_id="product-abc",
            status="IN_PROGRESS",
            updated_at=stuck_time,
            created_at=stuck_time,
        )
        mission_error = Mission(
            id=str(uuid.uuid4()),
            tenant_id="stuck-test.myshopify.com",
            resource_id="product-def",
            status="ERROR",
            error_message="OpenAI timeout after 3 retries",
            updated_at=stuck_time,
            created_at=stuck_time,
        )
        mission_ok = Mission(
            id=str(uuid.uuid4()),
            tenant_id="stuck-test.myshopify.com",
            resource_id="product-ghi",
            status="COMPLETED",
            completed_at=datetime.now(timezone.utc),
        )
        db.add_all([mission_stuck, mission_error, mission_ok])
        db.commit()

        stuck_id = mission_stuck.id
        error_id = mission_error.id
        ok_id = mission_ok.id
        db.close()

        # Step 1: Detect stuck missions
        resp = client.get("/api/superadmin/missions/stuck", headers=_auth(token))
        assert resp.status_code == 200
        stuck_data = resp.json()
        assert stuck_data["count"] == 2
        stuck_ids = {m["id"] for m in stuck_data["stuck_missions"]}
        assert stuck_id in stuck_ids
        assert error_id in stuck_ids
        assert ok_id not in stuck_ids

        # Step 2: Recover the IN_PROGRESS mission
        resp = client.post(
            f"/api/superadmin/missions/{stuck_id}/recover",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["previous_status"] == "IN_PROGRESS"
        assert resp.json()["new_status"] == "PENDING"

        # Step 3: Recover the ERROR mission
        resp = client.post(
            f"/api/superadmin/missions/{error_id}/recover",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["previous_status"] == "ERROR"
        assert resp.json()["new_status"] == "PENDING"

        # Step 4: Verify stuck count is now 0
        resp = client.get("/api/superadmin/missions/stuck", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

        # Step 5: Verify missions list shows them as PENDING
        resp = client.get(
            "/api/superadmin/missions?status=PENDING",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        pending_ids = {m["id"] for m in resp.json()["missions"]}
        assert stuck_id in pending_ids
        assert error_id in pending_ids

    def test_recover_completed_mission_fails(self, client):
        """Attempting to recover a COMPLETED mission returns 400."""
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        shop = Shop(domain="ok-shop.myshopify.com", access_token="t", current_plan_name="Free", is_active=True)
        db.add(shop)
        m = Mission(
            id=str(uuid.uuid4()),
            tenant_id="ok-shop.myshopify.com",
            resource_id="p1",
            status="COMPLETED",
        )
        db.add(m)
        db.commit()
        mid = m.id
        db.close()

        resp = client.post(f"/api/superadmin/missions/{mid}/recover", headers=_auth(token))
        assert resp.status_code == 400

    def test_recover_awaiting_approval_fails(self, client):
        """AWAITING_APPROVAL missions should not be recoverable."""
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        shop = Shop(domain="await-shop.myshopify.com", access_token="t", current_plan_name="Pro", is_active=True)
        db.add(shop)
        m = Mission(
            id=str(uuid.uuid4()),
            tenant_id="await-shop.myshopify.com",
            resource_id="p2",
            status="AWAITING_APPROVAL",
        )
        db.add(m)
        db.commit()
        mid = m.id
        db.close()

        resp = client.post(f"/api/superadmin/missions/{mid}/recover", headers=_auth(token))
        assert resp.status_code == 400
        assert "AWAITING_APPROVAL" in resp.json()["detail"]


# ===================================================================
# Integration: Concern Lifecycle
# ===================================================================

class TestConcernLifecycle:
    """
    Scenario: A merchant submits a concern. Admin sees it in the list,
    replies, and the status updates to 'replied'.
    """

    def test_submit_view_reply_flow(self, client):
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        shop = Shop(domain="concern-shop.myshopify.com", access_token="t", current_plan_name="Basic", is_active=True)
        db.add(shop)
        db.commit()
        db.close()

        # Step 1: Merchant submits a concern (via the admin endpoint)
        resp = client.post(
            "/api/admin/submit-concern",
            json={
                "subject": "Images not loading",
                "message": "When I optimize my product, images disappear after save.",
                "email": "merchant@example.com",
            },
            headers={"X-Shopify-Shop-Domain": "concern-shop.myshopify.com"},
        )
        assert resp.status_code == 200
        concern_id = resp.json()["concern_id"]

        # Step 2: Admin views concerns
        resp = client.get("/api/superadmin/concerns", headers=_auth(token))
        assert resp.status_code == 200
        concerns = resp.json()["concerns"]
        submitted = next((c for c in concerns if c["id"] == concern_id), None)
        assert submitted is not None
        assert submitted["status"] == "open"
        assert submitted["subject"] == "Images not loading"
        assert submitted["shop_domain"] == "concern-shop.myshopify.com"

        # Step 3: Admin replies
        resp = client.post(
            f"/api/superadmin/concerns/{concern_id}/reply",
            json={"reply": "Thanks for reporting. We've pushed a fix. Please clear cache and retry."},
            headers=_auth(token),
        )
        assert resp.status_code == 200

        # Step 4: Verify status changed to 'replied'
        resp = client.get("/api/superadmin/concerns", headers=_auth(token))
        assert resp.status_code == 200
        updated = next((c for c in resp.json()["concerns"] if c["id"] == concern_id), None)
        assert updated is not None
        assert updated["status"] == "replied"
        assert "pushed a fix" in updated["admin_reply"]

    def test_multiple_concerns_ordering(self, client):
        """Multiple concerns show up newest first."""
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        shop = Shop(domain="multi-concern.myshopify.com", access_token="t", current_plan_name="Free", is_active=True)
        db.add(shop)
        db.commit()

        for i in range(5):
            c = ConcernLog(
                shop_domain="multi-concern.myshopify.com",
                email="x@test.com",
                subject=f"Issue #{i}",
                message=f"Description for issue {i}",
                status="open",
            )
            db.add(c)
        db.commit()
        db.close()

        resp = client.get("/api/superadmin/concerns", headers=_auth(token))
        assert resp.status_code == 200
        concerns = resp.json()["concerns"]
        assert len(concerns) == 5


# ===================================================================
# Integration: Outreach Lifecycle
# ===================================================================

class TestOutreachLifecycle:
    """
    Scenario: Admin composes an email to multiple merchants,
    sends it, and verifies it shows up in history.
    """

    def test_send_and_verify_history(self, client):
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        shop1 = Shop(domain="reach-1.myshopify.com", access_token="t", current_plan_name="Pro", is_active=True)
        shop2 = Shop(domain="reach-2.myshopify.com", access_token="t", current_plan_name="Basic", is_active=True)
        db.add_all([shop1, shop2])
        db.commit()
        db.close()

        # Step 1: Send to direct emails + merchant domains
        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": ["external@partner.com"],
                "merchant_domains": ["reach-1.myshopify.com", "reach-2.myshopify.com"],
                "subject": "New Feature: AI Image Refinement",
                "body": "We're excited to announce a new AI-powered image refinement feature...",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recipients"] == 3  # 1 email + 2 domains
        assert data["status"] == "dummy"

        # Step 2: Verify history
        resp = client.get("/api/superadmin/outreach/history", headers=_auth(token))
        assert resp.status_code == 200
        history = resp.json()["history"]
        assert resp.json()["total"] == 3
        subjects = {h["subject"] for h in history}
        assert "New Feature: AI Image Refinement" in subjects

    def test_send_empty_recipients_fails(self, client):
        token = _get_token(client)
        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "to_emails": [],
                "merchant_domains": [],
                "subject": "Test",
                "body": "Test",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_send_nonexistent_domain_ignored(self, client):
        """Sending to a domain not in the DB should still work — just no match."""
        _reset_tables()
        token = _get_token(client)

        resp = client.post(
            "/api/superadmin/outreach/send",
            json={
                "merchant_domains": ["ghost-shop.myshopify.com"],
                "subject": "Hello",
                "body": "Test",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 400  # no recipients resolved


# ===================================================================
# Integration: Dashboard Aggregation with Multi-Merchant Data
# ===================================================================

class TestDashboardAggregation:
    """
    Scenario: Multiple merchants with different plans, usage patterns,
    and cost accumulations. Dashboard should aggregate correctly.
    """

    def test_multi_merchant_overview(self, client):
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        # Free merchant with low usage
        db.add(Shop(
            domain="free-user.myshopify.com", access_token="t",
            current_plan_name="Free", is_active=True,
            monthly_rewrites_used=3, monthly_missions_used=1,
            monthly_image_generations_used=0,
        ))
        # Pro merchant with high usage
        db.add(Shop(
            domain="pro-user.myshopify.com", access_token="t",
            current_plan_name="Pro", is_active=True,
            monthly_rewrites_used=120, monthly_missions_used=25,
            monthly_image_generations_used=80,
        ))
        # Churned merchant
        db.add(Shop(
            domain="gone-user.myshopify.com", access_token="t",
            current_plan_name="Free", is_active=False,
            last_uninstalled_at=datetime.now(timezone.utc),
        ))

        # Add usage events
        for i in range(5):
            db.add(UsageEventLog(
                shop_domain="pro-user.myshopify.com",
                plan_name="Pro",
                event_type="rewrite",
                feature="product_rewrite",
                total_tokens=1000,
                prompt_tokens=400,
                completion_tokens=600,
                estimated_cost_usd=0.01,
            ))
        db.add(UsageEventLog(
            shop_domain="free-user.myshopify.com",
            plan_name="Free",
            event_type="rewrite",
            feature="product_rewrite",
            total_tokens=200,
            prompt_tokens=100,
            completion_tokens=100,
            estimated_cost_usd=0.002,
        ))

        # Missions
        db.add(Mission(id=str(uuid.uuid4()), tenant_id="pro-user.myshopify.com", resource_id="p1", status="COMPLETED"))
        db.add(Mission(id=str(uuid.uuid4()), tenant_id="pro-user.myshopify.com", resource_id="p2", status="COMPLETED"))
        db.add(Mission(id=str(uuid.uuid4()), tenant_id="free-user.myshopify.com", resource_id="p3", status="ERROR"))

        db.commit()
        db.close()

        # Overview
        resp = client.get("/api/superadmin/dashboard/overview", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_merchants"] == 3
        assert data["total_missions"] == 3
        assert data["total_image_generations"] == 80
        assert data["total_estimated_cost_usd"] > 0

        # Plan stats
        resp = client.get("/api/superadmin/dashboard/plan-stats", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["enrollment"]["Free"] == 2
        assert data["enrollment"]["Pro"] == 1
        assert data["churned_count"] == 1

        # Token usage
        resp = client.get("/api/superadmin/dashboard/token-usage", headers=_auth(token))
        assert resp.status_code == 200
        entries = resp.json()
        pro_entry = next((e for e in entries if e["shop_domain"] == "pro-user.myshopify.com"), None)
        assert pro_entry is not None
        assert pro_entry["total_tokens"] == 5000

        # Image credits
        resp = client.get("/api/superadmin/dashboard/image-credits", headers=_auth(token))
        assert resp.status_code == 200
        img_data = resp.json()
        pro_img = next((d for d in img_data if d["shop_domain"] == "pro-user.myshopify.com"), None)
        assert pro_img is not None
        assert pro_img["monthly_used"] == 80

    def test_merchant_drill_down(self, client):
        """After seeing a merchant in the overview, drill into their detail."""
        token = _get_token(client)

        # List merchants
        resp = client.get("/api/superadmin/merchants?search=pro-user", headers=_auth(token))
        assert resp.status_code == 200
        merchants = resp.json()["merchants"]
        assert len(merchants) >= 1

        # Drill into detail
        resp = client.get(
            "/api/superadmin/merchants/pro-user.myshopify.com",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["shop"]["domain"] == "pro-user.myshopify.com"
        assert detail["shop"]["current_plan_name"] == "Pro"
        assert len(detail["recent_events"]) >= 5
        assert len(detail["missions"]) >= 2


# ===================================================================
# Integration: Plan Change Tracking
# ===================================================================

class TestPlanChangeTracking:
    def test_plan_changes_visible_in_stats(self, client):
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        now = datetime.now(timezone.utc)
        db.add(Shop(
            domain="upgrader.myshopify.com", access_token="t",
            current_plan_name="Pro",
            last_plan_name="Free",
            last_plan_change_type="upgrade",
            last_plan_change_at=now - timedelta(days=2),
            is_active=True,
        ))
        db.add(Shop(
            domain="downgrader.myshopify.com", access_token="t",
            current_plan_name="Basic",
            last_plan_name="Pro",
            last_plan_change_type="downgrade",
            last_plan_change_at=now - timedelta(days=1),
            is_active=True,
        ))
        db.commit()
        db.close()

        resp = client.get("/api/superadmin/dashboard/plan-stats", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        changes = data["recent_changes"]
        assert len(changes) >= 2

        types = {ch["change_type"] for ch in changes}
        assert "upgrade" in types
        assert "downgrade" in types

        # Downgrader is more recent, so it should be first
        assert changes[0]["shop_domain"] == "downgrader.myshopify.com"


# ===================================================================
# Integration: Auth Lifecycle
# ===================================================================

class TestAuthLifecycle:
    def test_login_then_access_then_expire(self, client):
        """Full auth lifecycle: login → use → expired token rejected."""
        # Step 1: Login
        resp = client.post("/api/superadmin/login", json={
            "username": ADMIN_USERNAME,
            "password": ADMIN_PASSWORD,
        })
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        # Step 2: Use the token
        resp = client.get("/api/superadmin/dashboard/overview", headers=_auth(token))
        assert resp.status_code == 200

        # Step 3: Craft an expired token
        expired_token = jwt.encode(
            {"sub": "admin", "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
            ADMIN_JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        resp = client.get("/api/superadmin/dashboard/overview", headers=_auth(expired_token))
        assert resp.status_code == 401

    def test_tampered_token_rejected(self, client):
        """A token signed with wrong secret is rejected."""
        bad_token = jwt.encode(
            {"sub": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            "wrong-secret",
            algorithm=JWT_ALGORITHM,
        )
        resp = client.get("/api/superadmin/dashboard/overview", headers=_auth(bad_token))
        assert resp.status_code == 401

    def test_wrong_credentials_denied(self, client):
        resp = client.post("/api/superadmin/login", json={
            "username": "hacker",
            "password": "password123",
        })
        assert resp.status_code == 401
        # Subsequent access should still fail
        resp = client.get("/api/superadmin/dashboard/overview")
        assert resp.status_code == 422  # Missing header


# ===================================================================
# Integration: Feature Usage Tracking
# ===================================================================

class TestFeatureUsageTracking:
    def test_feature_usage_aggregation(self, client):
        _reset_tables()
        token = _get_token(client)
        db = TestingSessionLocal()

        from datetime import date
        db.add(FeatureUsage(
            shop_domain="feat-shop.myshopify.com",
            feature="product_rewrite",
            billing_cycle_start=date(2025, 1, 1),
            usage_count=50,
        ))
        db.add(FeatureUsage(
            shop_domain="feat-shop.myshopify.com",
            feature="image_generation",
            billing_cycle_start=date(2025, 1, 1),
            usage_count=10,
        ))
        db.add(FeatureUsage(
            shop_domain="other-shop.myshopify.com",
            feature="product_rewrite",
            billing_cycle_start=date(2025, 1, 1),
            usage_count=20,
        ))
        db.commit()
        db.close()

        resp = client.get("/api/superadmin/dashboard/feature-usage", headers=_auth(token))
        assert resp.status_code == 200
        features = resp.json()
        rewrite = next((f for f in features if f["feature"] == "product_rewrite"), None)
        assert rewrite is not None
        assert rewrite["total_usage"] == 70
        assert rewrite["unique_shops"] == 2

        img = next((f for f in features if f["feature"] == "image_generation"), None)
        assert img is not None
        assert img["total_usage"] == 10
        assert img["unique_shops"] == 1

"""
Integration tests for the missions endpoint with ad-hoc agent selection.

Tests the /api/missions endpoint's ability to handle:
- Ad-hoc agent selection via requested_agents
- Full workflow when no requested_agents specified
- Edge cases and validation
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import Plan, User, Shop, Mission
from src.main.security.security import verify_shopify_session
from src.main.api.shopify.shared import resolve_shop_domain


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


async def override_verify_session():
    """Mock verify_shopify_session to return dev shop domain."""
    return "dev-shop.myshopify.com"


def override_resolve_shop_domain():
    """Mock resolve_shop_domain dependency."""
    return "dev-shop.myshopify.com"


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_shopify_session] = override_verify_session
    app.dependency_overrides[resolve_shop_domain] = override_resolve_shop_domain
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    del app.dependency_overrides[get_db]
    del app.dependency_overrides[verify_shopify_session]
    del app.dependency_overrides[resolve_shop_domain]
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def seed_shop():
    """Seed the dev-shop for testing."""
    db = TestingSessionLocal()
    db.query(User).delete()
    db.query(Shop).delete()
    db.query(Plan).delete()
    db.query(Mission).delete()
    db.commit()

    plan = Plan(name="Pro", monthly_rewrite_limit=1000, max_request_rate=100, can_stream_responses=True)
    db.add(plan)
    db.commit()

    user = User(username="dev-shop.myshopify.com", plan_id=plan.id)
    db.add(user)
    db.commit()
    
    now = datetime.now(timezone.utc)
    db.add(
        Shop(
            domain="dev-shop.myshopify.com",
            access_token="dev-token-123",
            monthly_rewrites_used=0,
            reset_anchor_date=now,
            next_reset_date=now + timedelta(days=30),
            current_plan_name="Pro",
            last_plan_name="Pro",
            access_expires_at=now + timedelta(days=30),
        )
    )
    db.commit()
    db.close()


def _auth_headers():
    return {"Authorization": "Bearer dev-token-123", "Content-Type": "application/json"}


# =============================================================================
# Tests: Create Mission with Ad-hoc Agents
# =============================================================================

class TestCreateMissionAdhoc:
    """Tests for creating missions with ad-hoc agent selection."""

    def test_create_mission_with_no_requested_agents(self, client, seed_shop):
        """Test creating a mission without ad-hoc agents (full workflow)."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-123",
                "product_name": "Test Product",
                "japanese_description": "テスト商品の説明",
                "category": "Kitchenware",
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "created"
        assert "mission_id" in body
        assert "stream_url" in body
        assert body["is_adhoc"] is False
        assert body["requested_agents"] is None

    def test_create_mission_with_single_agent(self, client, seed_shop):
        """Test creating a mission with single ad-hoc agent."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-123",
                "product_name": "Test Product",
                "japanese_description": "テスト商品の説明",
                "requested_agents": ["CopywriterAgent"],
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "created"
        assert body["is_adhoc"] is True
        assert body["requested_agents"] == ["CopywriterAgent"]

    def test_create_mission_with_marketing_agent(self, client, seed_shop):
        """Test creating a mission with MarketingAgent only."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-456",
                "product_name": "Premium Bowl",
                "japanese_description": "高級な陶器ボウル",
                "requested_agents": ["MarketingAgent"],
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_adhoc"] is True
        assert body["requested_agents"] == ["MarketingAgent"]

    def test_create_mission_with_price_scout_agent(self, client, seed_shop):
        """Test creating a mission with PriceScoutAgent only."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-789",
                "product_name": "Ceramic Vase",
                "japanese_description": "美しい陶器の花瓶",
                "requested_agents": ["PriceScoutAgent"],
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_adhoc"] is True
        assert body["requested_agents"] == ["PriceScoutAgent"]

    def test_create_mission_with_compliance_agent(self, client, seed_shop):
        """Test creating a mission with ComplianceAgent only."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-101",
                "product_name": "Health Supplement",
                "japanese_description": "健康サプリメント",
                "requested_agents": ["ComplianceAgent"],
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_adhoc"] is True
        assert body["requested_agents"] == ["ComplianceAgent"]

    def test_create_mission_with_multiple_agents(self, client, seed_shop):
        """Test creating a mission with multiple ad-hoc agents."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-202",
                "product_name": "Kitchen Set",
                "japanese_description": "キッチンセット",
                "requested_agents": ["MarketingAgent", "ComplianceAgent"],
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_adhoc"] is True
        assert body["requested_agents"] == ["MarketingAgent", "ComplianceAgent"]
        assert len(body["requested_agents"]) == 2

    def test_create_mission_with_all_agents(self, client, seed_shop):
        """Test creating a mission with all agents specified."""
        all_agents = ["CopywriterAgent", "MarketingAgent", "PriceScoutAgent", "ComplianceAgent"]
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-303",
                "product_name": "Complete Product",
                "japanese_description": "完全な商品",
                "requested_agents": all_agents,
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_adhoc"] is True
        assert body["requested_agents"] == all_agents

    def test_create_mission_with_empty_agents_list(self, client, seed_shop):
        """Test creating a mission with empty requested_agents list."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-404",
                "product_name": "Empty Test",
                "japanese_description": "空のテスト",
                "requested_agents": [],
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        # Empty list should be treated as not ad-hoc
        assert body["is_adhoc"] is False


# =============================================================================
# Tests: Mission State Storage
# =============================================================================

class TestMissionStateStorage:
    """Tests for verifying mission state includes ad-hoc info."""

    def test_mission_record_stores_requested_agents(self, client, seed_shop):
        """Test that mission record stores requested_agents in initial_state."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-store-test",
                "product_name": "Storage Test",
                "japanese_description": "ストレージテスト",
                "requested_agents": ["CopywriterAgent", "MarketingAgent"],
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        mission_id = body["mission_id"]
        
        # Verify in database
        db = TestingSessionLocal()
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        
        assert mission is not None
        assert mission.current_state is not None
        assert mission.current_state.get("requested_agents") == ["CopywriterAgent", "MarketingAgent"]
        assert mission.current_state.get("is_adhoc") is True
        
        db.close()

    def test_mission_record_stores_null_for_full_workflow(self, client, seed_shop):
        """Test that mission record stores None for full workflow."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-full-workflow",
                "product_name": "Full Workflow Test",
                "japanese_description": "完全ワークフローテスト",
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        mission_id = body["mission_id"]
        
        # Verify in database
        db = TestingSessionLocal()
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        
        assert mission is not None
        assert mission.current_state.get("requested_agents") is None
        assert mission.current_state.get("is_adhoc") is False
        
        db.close()


# =============================================================================
# Tests: Request Validation
# =============================================================================

class TestMissionRequestValidation:
    """Tests for mission request validation."""

    def test_missing_product_id_returns_422(self, client, seed_shop):
        """Test that missing product_id returns 422."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_name": "Test Product",
                "japanese_description": "テスト商品",
            },
        )
        
        assert resp.status_code == 422

    def test_missing_product_name_returns_422(self, client, seed_shop):
        """Test that missing product_name returns 422."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-123",
                "japanese_description": "テスト商品",
            },
        )
        
        assert resp.status_code == 422

    def test_missing_description_returns_422(self, client, seed_shop):
        """Test that missing japanese_description returns 422."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-123",
                "product_name": "Test Product",
            },
        )
        
        assert resp.status_code == 422

    def test_invalid_json_returns_400(self, client, seed_shop):
        """Test that invalid JSON returns 400."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            content="invalid json {",
        )
        
        assert resp.status_code == 400


# =============================================================================
# Tests: Get Mission Status
# =============================================================================

class TestGetMissionStatus:
    """Tests for getting mission status."""

    def test_get_mission_returns_adhoc_info(self, client, seed_shop):
        """Test that getting mission includes ad-hoc information."""
        # First create a mission
        create_resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-get-test",
                "product_name": "Get Test",
                "japanese_description": "取得テスト",
                "requested_agents": ["ComplianceAgent"],
            },
        )
        
        assert create_resp.status_code == 200
        mission_id = create_resp.json()["mission_id"]
        
        # Get mission status
        get_resp = client.get(
            f"/api/missions/{mission_id}",
            headers=_auth_headers(),
        )
        
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["mission_id"] == mission_id
        # The state should include the requested_agents
        if "current_state" in body:
            assert body["current_state"].get("requested_agents") == ["ComplianceAgent"]

    def test_get_nonexistent_mission_returns_404(self, client, seed_shop):
        """Test that getting a non-existent mission returns 404."""
        get_resp = client.get(
            "/api/missions/nonexistent-mission-id",
            headers=_auth_headers(),
        )
        
        assert get_resp.status_code == 404


# =============================================================================
# Tests: Different Tiers with Ad-hoc
# =============================================================================

class TestAdhocWithDifferentTiers:
    """Tests for ad-hoc agent selection with different subscription tiers."""

    @pytest.fixture
    def seed_free_shop(self):
        """Seed a Free tier shop."""
        db = TestingSessionLocal()
        db.query(User).delete()
        db.query(Shop).delete()
        db.query(Plan).delete()
        db.commit()

        plan = Plan(name="Free", monthly_rewrite_limit=10, max_request_rate=10)
        db.add(plan)
        db.commit()

        user = User(username="dev-shop.myshopify.com", plan_id=plan.id)
        db.add(user)
        db.commit()
        
        now = datetime.now(timezone.utc)
        db.add(
            Shop(
                domain="dev-shop.myshopify.com",
                access_token="dev-token-123",
                monthly_rewrites_used=0,
                reset_anchor_date=now,
                next_reset_date=now + timedelta(days=30),
                current_plan_name="Free",
            )
        )
        db.commit()
        db.close()

    def test_free_tier_can_use_adhoc(self, client, seed_free_shop):
        """Test that Free tier can use ad-hoc agent selection."""
        resp = client.post(
            "/api/missions",
            headers=_auth_headers(),
            json={
                "product_id": "prod-free-adhoc",
                "product_name": "Free Tier Test",
                "japanese_description": "無料プランテスト",
                "requested_agents": ["MarketingAgent"],
            },
        )
        
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_adhoc"] is True
        assert body["requested_agents"] == ["MarketingAgent"]

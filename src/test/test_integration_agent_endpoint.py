import pytest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from src.ecommerce.api.main import app
from src.shared.db.database import Base, get_db
from src.ecommerce.db.models import Plan, User, Shop
from src.shared.security.security import verify_shopify_session


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


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_shopify_session] = override_verify_session
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    del app.dependency_overrides[get_db]
    del app.dependency_overrides[verify_shopify_session]
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def seed_shop():
    """
    Seed the dev-shop used by security.verify_shopify_session("Bearer dev-token-123").
    """
    db = TestingSessionLocal()
    db.query(User).delete()
    db.query(Shop).delete()
    db.query(Plan).delete()
    db.commit()

    plan = Plan(name="Pro", monthly_rewrite_limit=1000, max_request_rate=100, can_stream_responses=True)
    db.add(plan)
    db.commit()

    user = User(username="dev-shop.myshopify.com", plan_id=plan.id)
    db.add(user)
    db.commit()
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    # Seed paid grace-period fields so the shop is not considered "expired_paid".
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


def test_agent_endpoint_social_hook_happy_path(client, seed_shop, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # Auth is handled by dependency override in fixture
    resp = client.post(
        "/apps/cross-border/agent",
        headers=_auth_headers(),
        json={
            "action": "social_hook_architect",
            "context": {"focus": "Instagram Reels"},
            "product_data": {"title": "Test Product", "category": "General"},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "text" in body["data"]
    assert "metadata" in body["data"]
    assert len(body["data"]["metadata"]["hooks"]) == 3


def test_agent_endpoint_seasonal_happy_path(client, seed_shop):
    # Auth is handled by dependency override in fixture
    resp = client.post(
        "/apps/cross-border/agent",
        headers=_auth_headers(),
        json={
            "action": "seasonal_campaign_agent",
            "context": {"current_date": "2026-04-10T00:00:00Z"},
            "product_data": {"category": "Skincare"},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "campaign" in body["data"]["metadata"]
    assert "title" in body["data"]["metadata"]["campaign"]


def test_agent_endpoint_seasonal_caption_happy_path(client, seed_shop, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Auth is handled by dependency override in fixture
    resp = client.post(
        "/apps/cross-border/agent",
        headers=_auth_headers(),
        json={
            "action": "seasonal_campaign_caption",
            "context": {"current_date": "2026-04-10T00:00:00Z"},
            "product_data": {"title": "Test Product", "category": "General", "tags": ["gift"]},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "copy_text" in body["data"]["metadata"]


def test_agent_endpoint_value_discovery_happy_path(client, seed_shop):
    # Auth is handled by dependency override in fixture
    resp = client.post(
        "/apps/cross-border/agent",
        headers=_auth_headers(),
        json={
            "action": "value_discovery",
            "context": {},
            "product_data": {"title": "Kyoto bowl", "description": "Made in Kyoto."},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert isinstance(body["data"]["metadata"]["discoveries"], list)

def test_agent_endpoint_unknown_action_returns_400(client, seed_shop):
    # Auth is handled by dependency override in fixture
    resp = client.post(
        "/apps/cross-border/agent",
        headers=_auth_headers(),
        json={"action": "nope", "context": {}, "product_data": {}},
    )
    assert resp.status_code == 400


def test_agent_endpoint_invalid_json_returns_400(client, seed_shop):
    # Auth is handled by dependency override in fixture
    resp = client.post(
        "/apps/cross-border/agent",
        headers={"Authorization": "Bearer dev-token-123", "Content-Type": "text/plain"},
        data="not-json",
    )
    assert resp.status_code == 400


def test_agent_endpoint_invalid_token_returns_401(seed_shop):
    """Test that invalid token returns 401 - uses separate client without auth override."""
    # Create a separate client without the verify_shopify_session override
    app.dependency_overrides[get_db] = override_get_db
    # Remove auth override temporarily if it exists
    original_override = app.dependency_overrides.pop(verify_shopify_session, None)
    
    with TestClient(app, raise_server_exceptions=False) as test_client:
        with patch("src.shared.security.security.SHOPIFY_API_KEY", "test-key"), \
             patch("src.shared.security.security.SHOPIFY_API_SECRET", "test-secret"):
            resp = test_client.post(
                "/apps/cross-border/agent",
                headers={"Authorization": "Bearer not-a-real-token"},
                json={"action": "social_hook_architect", "context": {}, "product_data": {}},
            )
    
    # Restore override
    if original_override:
        app.dependency_overrides[verify_shopify_session] = original_override
    
    assert resp.status_code == 401


def test_agent_endpoint_quota_exceeded_returns_403(client, seed_shop):
    db = TestingSessionLocal()
    user = db.query(User).filter_by(username="dev-shop.myshopify.com").first()
    assert user is not None
    shop = db.query(Shop).filter_by(domain="dev-shop.myshopify.com").first()
    assert shop is not None
    shop.monthly_rewrites_used = 1000
    db.commit()
    db.close()

    # Auth is handled by dependency override in fixture
    resp = client.post(
        "/apps/cross-border/agent",
        headers=_auth_headers(),
        json={"action": "social_hook_architect", "context": {}, "product_data": {}},
    )
    assert resp.status_code == 403



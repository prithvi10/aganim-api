import pytest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import Plan, User, UsageRecord


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
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    del app.dependency_overrides[get_db]
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def seed_shop():
    """
    Seed the dev-shop used by security.verify_shopify_session("Bearer dev-token-123").
    """
    db = TestingSessionLocal()
    db.query(UsageRecord).delete()
    db.query(User).delete()
    db.query(Plan).delete()
    db.commit()

    plan = Plan(name="Pro", monthly_token_quota=1000, max_request_rate=100, can_stream_responses=True)
    db.add(plan)
    db.commit()

    user = User(username="dev-shop.myshopify.com", plan_id=plan.id)
    db.add(user)
    db.commit()
    db.close()


def _auth_headers():
    return {"Authorization": "Bearer dev-token-123", "Content-Type": "application/json"}


def test_agent_endpoint_social_hook_happy_path(client, seed_shop, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch("src.main.security.security.SHOPIFY_API_KEY", "test-key"), patch(
        "src.main.security.security.SHOPIFY_API_SECRET", "test-secret"
    ):
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
    with patch("src.main.security.security.SHOPIFY_API_KEY", "test-key"), patch(
        "src.main.security.security.SHOPIFY_API_SECRET", "test-secret"
    ):
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


def test_agent_endpoint_unknown_action_returns_400(client, seed_shop):
    with patch("src.main.security.security.SHOPIFY_API_KEY", "test-key"), patch(
        "src.main.security.security.SHOPIFY_API_SECRET", "test-secret"
    ):
        resp = client.post(
            "/apps/cross-border/agent",
            headers=_auth_headers(),
            json={"action": "nope", "context": {}, "product_data": {}},
        )
    assert resp.status_code == 400


def test_agent_endpoint_invalid_json_returns_400(client, seed_shop):
    with patch("src.main.security.security.SHOPIFY_API_KEY", "test-key"), patch(
        "src.main.security.security.SHOPIFY_API_SECRET", "test-secret"
    ):
        resp = client.post(
            "/apps/cross-border/agent",
            headers={"Authorization": "Bearer dev-token-123", "Content-Type": "text/plain"},
            data="not-json",
        )
    assert resp.status_code == 400


def test_agent_endpoint_invalid_token_returns_401(client, seed_shop):
    with patch("src.main.security.security.SHOPIFY_API_KEY", "test-key"), patch(
        "src.main.security.security.SHOPIFY_API_SECRET", "test-secret"
    ):
        resp = client.post(
            "/apps/cross-border/agent",
            headers={"Authorization": "Bearer not-a-real-token"},
            json={"action": "social_hook_architect", "context": {}, "product_data": {}},
        )
    assert resp.status_code == 401


def test_agent_endpoint_quota_exceeded_returns_429(client, seed_shop):
    db = TestingSessionLocal()
    user = db.query(User).filter_by(username="dev-shop.myshopify.com").first()
    assert user is not None
    today = date.today()
    cycle_start = date(today.year, today.month, 1)
    # monthly_token_quota is 1000, so this blocks all requests
    db.add(UsageRecord(user_id=user.id, billing_cycle_start=cycle_start, token_count=1000))
    db.commit()
    db.close()

    with patch("src.main.security.security.SHOPIFY_API_KEY", "test-key"), patch(
        "src.main.security.security.SHOPIFY_API_SECRET", "test-secret"
    ):
        resp = client.post(
            "/apps/cross-border/agent",
            headers=_auth_headers(),
            json={"action": "social_hook_architect", "context": {}, "product_data": {}},
        )
    assert resp.status_code == 429



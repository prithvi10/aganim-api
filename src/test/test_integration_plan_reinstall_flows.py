import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.ecommerce.api.main import app
from src.shared.db.database import Base, get_db
from src.ecommerce.db.models import Plan, Shop, User


MOCK_SHOPIFY_SECRET = "test_secret_key"


def _generate_hmac(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _seed_plans(db):
    # Free (lifetime)
    if not db.query(Plan).filter_by(name="Free").first():
        db.add(
            Plan(
                name="Free",
                product_limit=10,
                monthly_rewrite_limit=10,
                billing_cycle_type="lifetime",
                max_request_rate=30,
            )
        )
    # Basic/Standard/Pro (recurring)
    if not db.query(Plan).filter_by(name="Basic").first():
        db.add(
            Plan(
                name="Basic",
                product_limit=50,
                monthly_rewrite_limit=50,
                billing_cycle_type="recurring",
                max_request_rate=30,
            )
        )
    if not db.query(Plan).filter_by(name="Standard").first():
        db.add(
            Plan(
                name="Standard",
                product_limit=100,
                monthly_rewrite_limit=100,
                billing_cycle_type="recurring",
                max_request_rate=60,
            )
        )
    if not db.query(Plan).filter_by(name="Pro").first():
        db.add(
            Plan(
                name="Pro",
                product_limit=-1,
                monthly_rewrite_limit=-1,
                billing_cycle_type="recurring",
                max_request_rate=120,
            )
        )
    db.commit()


def _install(client: TestClient, shop_domain: str):
    payload = {"myshopify_domain": shop_domain}
    body = json.dumps(payload).encode("utf-8")
    headers = {"X-Shopify-Hmac-Sha256": _generate_hmac(MOCK_SHOPIFY_SECRET, body)}
    r = client.post("/webhooks/app/install", content=body, headers=headers)
    assert r.status_code == 200


def _uninstall(client: TestClient, shop_domain: str):
    payload = {"myshopify_domain": shop_domain}
    body = json.dumps(payload).encode("utf-8")
    headers = {"X-Shopify-Hmac-Sha256": _generate_hmac(MOCK_SHOPIFY_SECRET, body)}
    r = client.post("/webhooks/app/uninstalled", content=body, headers=headers)
    assert r.status_code == 200


def _activate_subscription(client: TestClient, shop_domain: str, plan_name: str):
    # Use the "manual/custom trigger" fallback supported by the webhook handler.
    payload = {"myshopify_domain": shop_domain, "billing_plan": plan_name}
    body = json.dumps(payload).encode("utf-8")
    headers = {"X-Shopify-Hmac-Sha256": _generate_hmac(MOCK_SHOPIFY_SECRET, body)}
    r = client.post("/webhooks/subscription-activated", content=body, headers=headers)
    assert r.status_code == 200


def _rewrite_success(client: TestClient, shop_domain: str):
    r = client.post(
        f"/api/proxy/generate-copy?shop={shop_domain}",
        json={"product_name": "Test Product", "japanese_description": "テストです"},
    )
    return r


@pytest.fixture
def integration_client(monkeypatch):
    # Patch secret used by verify_webhook_signature
    monkeypatch.setattr("src.shared.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET, raising=False)

    # In-memory DB (StaticPool so threads share the same DB)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    # Seed plans
    db_seed = TestingSessionLocal()
    _seed_plans(db_seed)
    db_seed.close()

    # Override dependency
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Mock generation so /api/proxy/generate-copy can be used for quota decrementing without OpenAI.
    async def _mock_generation_request(*args, **kwargs):
        return {"status": "success", "data": {"title": "ok", "description": "<p>ok</p>"}}

    # Patch in the proxy module where the function is used
    monkeypatch.setattr(
        "src.ecommerce.api.shopify.proxy.process_generation_request",
        _mock_generation_request,
        raising=True,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_free_auto_activated_expires_after_10_credits(integration_client):
    client, SessionLocal = integration_client
    shop = "free-expire.myshopify.com"

    _install(client, shop)

    # Free is auto-activated
    u = client.get(f"/api/admin/usage?shop={shop}")
    assert u.status_code == 200
    data = u.json()
    assert data["plan_name"] == "Free"
    assert data["billing_cycle_type"] == "lifetime"
    assert data["lifetime_rewrites_remaining"] == 10
    assert data["ui_language"] == "en"

    # 10 rewrites succeed
    for _ in range(10):
        r = _rewrite_success(client, shop)
        assert r.status_code == 200
        assert r.json().get("status") == "success"

    # 11th rewrite blocked
    r11 = _rewrite_success(client, shop)
    assert r11.status_code == 403

    # Remaining credits = 0
    u2 = client.get(f"/api/admin/usage?shop={shop}")
    assert u2.status_code == 200
    data2 = u2.json()
    assert data2["plan_name"] == "Free"
    assert data2["billing_cycle_type"] == "lifetime"
    assert data2["lifetime_rewrites_remaining"] == 0


def test_free_uninstall_reinstall_preserves_remaining_and_stays_blocked_when_exhausted(integration_client):
    client, SessionLocal = integration_client
    shop = "free-reinstall.myshopify.com"

    _install(client, shop)

    # Use 3 credits
    for _ in range(3):
        r = _rewrite_success(client, shop)
        assert r.status_code == 200

    u = client.get(f"/api/admin/usage?shop={shop}")
    assert u.status_code == 200
    assert u.json()["lifetime_rewrites_remaining"] == 7

    # Uninstall + reinstall must NOT reset credits
    _uninstall(client, shop)
    _install(client, shop)

    u2 = client.get(f"/api/admin/usage?shop={shop}")
    assert u2.status_code == 200
    data2 = u2.json()
    assert data2["plan_name"] == "Free"
    assert data2["billing_cycle_type"] == "lifetime"
    assert data2["lifetime_rewrites_remaining"] == 7
    # Free should never show grace_mode
    assert bool(data2.get("grace_mode")) is False

    # Exhaust credits then ensure rewrites are blocked even after reinstall
    for _ in range(7):
        r = _rewrite_success(client, shop)
        assert r.status_code == 200
    r_block = _rewrite_success(client, shop)
    assert r_block.status_code == 403

    _uninstall(client, shop)
    _install(client, shop)
    r_block2 = _rewrite_success(client, shop)
    assert r_block2.status_code == 403


def test_free_exhausted_then_upgrade_to_basic_sets_50_and_no_grace(integration_client):
    client, SessionLocal = integration_client
    shop = "free-to-basic.myshopify.com"

    _install(client, shop)

    # Exhaust 10 credits
    for _ in range(10):
        r = _rewrite_success(client, shop)
        assert r.status_code == 200
    assert _rewrite_success(client, shop).status_code == 403

    # Upgrade to Basic
    _activate_subscription(client, shop, "Basic")

    u = client.get(f"/api/admin/usage?shop={shop}")
    assert u.status_code == 200
    data = u.json()
    assert data["plan_name"] == "Basic"
    assert data["billing_cycle_type"] == "recurring"
    assert int(data["rewrite_limit"]) == 50
    assert bool(data.get("grace_mode")) is False

    # Now rewrites should succeed again (monthly bucket)
    r_ok = _rewrite_success(client, shop)
    assert r_ok.status_code == 200


def test_paid_uninstall_reinstall_activates_previous_plan_with_grace_mode(integration_client):
    client, SessionLocal = integration_client
    shop = "basic-reinstall-grace.myshopify.com"

    _install(client, shop)
    _activate_subscription(client, shop, "Basic")

    # Uninstall -> should set last_uninstalled_at, enabling grace_mode
    _uninstall(client, shop)

    u = client.get(f"/api/admin/usage?shop={shop}")
    assert u.status_code == 200
    data = u.json()
    assert data["plan_name"] == "Basic"
    assert bool(data.get("grace_mode")) is True

    # Reinstall pathfinder should activate previous plan and land on Home
    _install(client, shop)
    p = client.get(f"/api/admin/reinstall-path?shop={shop}")
    assert p.status_code == 200
    body = p.json()
    assert body["reason"] == "paid_grace_active"
    assert body["redirect_to"] == "/app"

    # Rewrites should work during grace
    r_ok = _rewrite_success(client, shop)
    assert r_ok.status_code == 200


def test_ui_language_get_and_put(integration_client):
    client, SessionLocal = integration_client
    shop = "ui-lang-test.myshopify.com"

    _install(client, shop)

    # Default ui_language should be "en"
    u = client.get(f"/api/admin/usage?shop={shop}")
    assert u.status_code == 200
    assert u.json()["ui_language"] == "en"

    # Switch to Japanese
    r = client.put("/api/admin/ui-language", json={"shop": shop, "ui_language": "ja"})
    assert r.status_code == 200
    assert r.json()["ui_language"] == "ja"

    # Verify persisted via usage endpoint
    u2 = client.get(f"/api/admin/usage?shop={shop}")
    assert u2.status_code == 200
    assert u2.json()["ui_language"] == "ja"

    # Switch back to English
    r2 = client.put("/api/admin/ui-language", json={"shop": shop, "ui_language": "en"})
    assert r2.status_code == 200
    assert r2.json()["ui_language"] == "en"

    # Invalid language rejected
    r3 = client.put("/api/admin/ui-language", json={"shop": shop, "ui_language": "fr"})
    assert r3.status_code == 400

    # Missing shop rejected
    r4 = client.put("/api/admin/ui-language", json={"ui_language": "en"})
    assert r4.status_code == 400

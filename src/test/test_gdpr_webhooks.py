import json
import hashlib
import hmac
import base64
from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import Plan, User, UsageRecord, Shop


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


MOCK_SHOPIFY_SECRET = "gdpr_test_secret"


def _generate_hmac(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@pytest.fixture
def seed_shop_records():
    """
    Seed a merchant with both `users` and `shops` rows, plus usage for current month.
    The GDPR shop/redact handler should delete all of these.
    """
    db = TestingSessionLocal()
    db.query(UsageRecord).delete()
    db.query(User).delete()
    db.query(Shop).delete()
    db.query(Plan).delete()
    db.commit()

    plan = Plan(name="Basic", monthly_rewrite_limit=1000, max_request_rate=100, can_stream_responses=False)
    db.add(plan)
    db.commit()

    shop_domain = "gdpr-store.myshopify.com"
    user = User(username=shop_domain, plan_id=plan.id)
    db.add(user)
    db.commit()
    db.refresh(user)

    # Usage row (composite key)
    today = date.today()
    cycle_start = date(today.year, today.month, 1)
    db.add(UsageRecord(user_id=user.id, billing_cycle_start=cycle_start, usage_count=123))
    db.add(Shop(domain=shop_domain, access_token="shpua_mock"))
    db.commit()
    db.close()
    return shop_domain


@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_gdpr_compliance_webhook_rejects_invalid_signature(client):
    raw = b'{"hello":"world"}'
    resp = client.post(
        "/api/webhooks/compliance",
        content=raw,
        headers={
            "X-Shopify-Topic": "customers/data_request",
            "X-Shopify-Shop-Domain": "gdpr-store.myshopify.com",
            "X-Shopify-Hmac-Sha256": "invalid",
        },
    )
    assert resp.status_code == 401


def test_gdpr_compliance_webhook_rejects_missing_hmac_header(client):
    raw = b"{}"
    resp = client.post(
        "/api/webhooks/compliance",
        content=raw,
        headers={
            "X-Shopify-Topic": "customers/data_request",
            "X-Shopify-Shop-Domain": "gdpr-store.myshopify.com",
        },
    )
    assert resp.status_code == 401


@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_gdpr_customers_data_request_acknowledged(client):
    payload = {"shop_id": 123, "customer": {"id": 999}}
    raw = json.dumps(payload).encode("utf-8")
    sig = _generate_hmac(MOCK_SHOPIFY_SECRET, raw)

    resp = client.post(
        "/api/webhooks/compliance",
        content=raw,
        headers={
            "X-Shopify-Topic": "customers/data_request",
            "X-Shopify-Shop-Domain": "gdpr-store.myshopify.com",
            "X-Shopify-Hmac-Sha256": sig,
            "X-Shopify-Webhook-Id": "wh_1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "No customer personal data stored" in body["message"]


@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_gdpr_customers_redact_acknowledged(client):
    payload = {"shop_id": 123, "customer": {"id": 999}}
    raw = json.dumps(payload).encode("utf-8")
    sig = _generate_hmac(MOCK_SHOPIFY_SECRET, raw)

    resp = client.post(
        "/api/webhooks/compliance",
        content=raw,
        headers={
            "X-Shopify-Topic": "customers/redact",
            "X-Shopify-Shop-Domain": "gdpr-store.myshopify.com",
            "X-Shopify-Hmac-Sha256": sig,
            "X-Shopify-Webhook-Id": "wh_2",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_gdpr_shop_redact_deletes_merchant_records(client, seed_shop_records):
    shop_domain = seed_shop_records

    payload = {"shop_id": 123, "shop_domain": shop_domain}
    raw = json.dumps(payload).encode("utf-8")
    sig = _generate_hmac(MOCK_SHOPIFY_SECRET, raw)

    resp = client.post(
        "/api/webhooks/compliance",
        content=raw,
        headers={
            "X-Shopify-Topic": "shop/redact",
            "X-Shopify-Shop-Domain": shop_domain,
            "X-Shopify-Hmac-Sha256": sig,
            "X-Shopify-Webhook-Id": "wh_3",
        },
    )
    assert resp.status_code == 200

    # Verify deletion (best-effort should have removed user, usage, shop rows)
    db = TestingSessionLocal()
    assert db.query(User).filter(User.username == shop_domain).first() is None
    assert db.query(Shop).filter(Shop.domain == shop_domain).first() is None
    # usage row should also be gone (no user left, so query by join isn't needed)
    assert db.query(UsageRecord).count() == 0
    db.close()


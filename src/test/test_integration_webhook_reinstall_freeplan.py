import json
import base64
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import Plan, Shop
from src.main.db.db_transactions import record_successful_rewrite


MOCK_SHOPIFY_SECRET = "test_secret_key"


def _generate_hmac(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@pytest.mark.asyncio
async def test_install_uninstall_reinstall_preserves_free_credits(monkeypatch):
    """
    Integration flow:
    1) POST /webhooks/app/install (new shop)
    2) decrement 1 credit
    3) POST /webhooks/app/uninstalled
    4) POST /webhooks/app/install (same shop)
    Assert lifetime credits remain at 9 (not reset to 10).
    """
    # Patch secret used by verify_webhook_signature
    monkeypatch.setattr("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET, raising=False)

    # In-memory DB
    # Use StaticPool so the in-memory DB is shared across threads (TestClient runs in a thread).
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    # Seed Free plan (needed for install handler to create a User with Free)
    db_seed = TestingSessionLocal()
    free = Plan(
        name="Free",
        product_limit=10,
        monthly_rewrite_limit=10,
        billing_cycle_type="lifetime",
        max_request_rate=30,
    )
    db_seed.add(free)
    db_seed.commit()
    db_seed.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    shop_domain = "reinstall-test.myshopify.com"

    with TestClient(app) as client:
        # 1) Install (new)
        install_payload = {"myshopify_domain": shop_domain}
        body = json.dumps(install_payload).encode("utf-8")
        headers = {"X-Shopify-Hmac-Sha256": _generate_hmac(MOCK_SHOPIFY_SECRET, body)}
        r1 = client.post("/webhooks/app/install", content=body, headers=headers)
        assert r1.status_code == 200

        db = TestingSessionLocal()
        shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        assert shop is not None
        assert int(shop.lifetime_rewrites_remaining or 0) == 10
        assert bool(getattr(shop, "is_active", True)) is True

        # 2) Decrement credit (simulate successful rewrite)
        record_successful_rewrite(db, shop_domain, amount=1)
        shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        assert int(shop.lifetime_rewrites_remaining or 0) == 9

        # 3) Uninstall
        uninstall_payload = {"myshopify_domain": shop_domain}
        body2 = json.dumps(uninstall_payload).encode("utf-8")
        headers2 = {"X-Shopify-Hmac-Sha256": _generate_hmac(MOCK_SHOPIFY_SECRET, body2)}
        r2 = client.post("/webhooks/app/uninstalled", content=body2, headers=headers2)
        assert r2.status_code == 200
        # Uninstall runs in a separate session; re-open to avoid stale ORM identity map.
        db.close()
        db = TestingSessionLocal()
        shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        assert shop is not None
        assert bool(getattr(shop, "is_active", True)) is False
        assert int(shop.lifetime_rewrites_remaining or 0) == 9

        # 4) Reinstall (same shop)
        r3 = client.post("/webhooks/app/install", content=body, headers=headers)
        assert r3.status_code == 200
        # Reinstall runs in a separate session; re-open to avoid stale ORM identity map.
        db.close()
        db = TestingSessionLocal()
        shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        assert shop is not None
        assert bool(getattr(shop, "is_active", False)) is True
        assert int(shop.lifetime_rewrites_remaining or 0) == 9
        db.close()

    # Cleanup override
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


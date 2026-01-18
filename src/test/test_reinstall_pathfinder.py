import pytest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import Plan, Shop, User


@pytest.mark.asyncio
async def test_reinstall_path_paid_grace_redirects_dashboard(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    db.add(Plan(name="Basic", product_limit=50, monthly_rewrite_limit=50, billing_cycle_type="recurring", max_request_rate=10))
    db.add(Plan(name="Free", product_limit=10, monthly_rewrite_limit=10, billing_cycle_type="lifetime", max_request_rate=10))
    db.commit()

    shop_domain = "paid-grace.myshopify.com"
    free = db.query(Plan).filter_by(name="Free").first()
    db.add(User(username=shop_domain, email=None, plan_id=free.id))
    now = datetime.now(timezone.utc)
    db.add(
        Shop(
            domain=shop_domain,
            access_token="",
            is_active=False,
            last_plan_name="Basic",
            current_plan_name="Basic",
            access_expires_at=now + timedelta(days=3),
            lifetime_rewrites_remaining=10,
            monthly_rewrites_used=0,
        )
    )
    db.commit()
    db.close()

    def override_get_db():
        d = TestingSessionLocal()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        r = client.get(f"/api/admin/reinstall-path?shop={shop_domain}")
        assert r.status_code == 200
        body = r.json()
        assert body["redirect_to"] == "/app/dashboard"
        assert body["reason"] == "paid_grace_active"

    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.mark.asyncio
async def test_reinstall_path_free_no_credits_redirects_pricing(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    db.add(Plan(name="Free", product_limit=10, monthly_rewrite_limit=10, billing_cycle_type="lifetime", max_request_rate=10))
    db.commit()

    shop_domain = "free-empty.myshopify.com"
    free = db.query(Plan).filter_by(name="Free").first()
    db.add(User(username=shop_domain, email=None, plan_id=free.id))
    db.add(
        Shop(
            domain=shop_domain,
            access_token="",
            is_active=False,
            last_plan_name="Free",
            current_plan_name="Free",
            lifetime_rewrites_remaining=0,
            monthly_rewrites_used=0,
        )
    )
    db.commit()
    db.close()

    def override_get_db():
        d = TestingSessionLocal()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        r = client.get(f"/api/admin/reinstall-path?shop={shop_domain}")
        assert r.status_code == 200
        body = r.json()
        assert body["redirect_to"] == "/app/pricing"
        assert body["reason"] == "free_no_credits"

    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


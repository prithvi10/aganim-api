import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from src.main.api.main import app
from src.main.api.shopify import admin as admin_module
from src.main.api.shopify.shared import resolve_shop_domain
from src.main.db.database import Base, get_db
from src.main.db.db_models import Shop

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=pool.StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_shop(domain: str) -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        db.query(Shop).filter(Shop.domain == domain).delete()
        db.add(Shop(domain=domain, access_token=""))
        db.commit()
    finally:
        db.close()


@pytest.fixture
def _overrides():
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(resolve_shop_domain, None)
    Base.metadata.drop_all(bind=engine)


def test_brand_context_status_idle(_overrides):
    shop = "brand-test.myshopify.com"
    _seed_shop(shop)
    app.dependency_overrides[resolve_shop_domain] = lambda: shop

    with TestClient(app) as client:
        resp = client.get(f"/api/admin/brand-context/status?shop={shop}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"


def test_brand_context_ingest_async_accepts_and_sets_ready(_overrides):
    shop = "brand-async.myshopify.com"
    _seed_shop(shop)
    app.dependency_overrides[resolve_shop_domain] = lambda: shop

    def _mock_run(*, shop_id: str, raw_texts: list[dict], job_id: str) -> None:
        db = TestingSessionLocal()
        try:
            rec = db.query(Shop).filter(Shop.domain == shop_id).first()
            if rec:
                rec.brand_context_status = "ready"
                rec.brand_context_job_id = job_id
                rec.brand_context_last_error = None
                rec.brand_context = {
                    "en": {"clean_text": "Summary ready", "pillars": []},
                    "ja": {"clean_text": "", "pillars": []},
                }
                db.add(rec)
                db.commit()
        finally:
            db.close()

    payload = {
        "brand_persona": "Heritage Storyteller",
        "core_pillars": ["Craft", "Origin"],
        "raw_text": "We are a Kyoto atelier.",
        "urls": [],
    }

    # Patch in the admin module where the function is used
    with patch.object(admin_module, "_run_brand_context_ingest", side_effect=_mock_run):
        with TestClient(app) as client:
            resp = client.post("/api/admin/brand-context/ingest-async", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "accepted"

            status = client.get(f"/api/admin/brand-context/status?shop={shop}")
            assert status.status_code == 200
            sdata = status.json()
            assert sdata["status"] == "ready"
            assert sdata["summary"] == "Summary ready"


def test_brand_context_ingest_async_missing_content(_overrides):
    shop = "brand-missing.myshopify.com"
    _seed_shop(shop)
    app.dependency_overrides[resolve_shop_domain] = lambda: shop

    with TestClient(app) as client:
        resp = client.post("/api/admin/brand-context/ingest-async", json={})
        assert resp.status_code == 400

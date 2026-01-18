from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import Shop, Plan, User
from src.main.db.db_transactions import record_successful_rewrite


def test_onboarding_update_step_persists_and_finishes():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    db.add(Plan(name="Free", monthly_rewrite_limit=10, max_request_rate=60, billing_cycle_type="lifetime"))
    db.commit()
    free = db.query(Plan).filter(Plan.name == "Free").first()
    assert free is not None
    db.add(User(username="onboarding-shop.myshopify.com", email=None, plan_id=free.id))
    db.add(Shop(domain="onboarding-shop.myshopify.com", access_token="x", is_active=True))
    db.commit()
    db.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            r1 = client.post(
                "/api/onboarding/update_step?shop=onboarding-shop.myshopify.com",
                json={"step": 2},
            )
            assert r1.status_code == 200
            assert r1.json()["onboarding_step"] == 2
            assert r1.json()["is_onboarding_finished"] is False

            r2 = client.post(
                "/api/onboarding/update_step?shop=onboarding-shop.myshopify.com",
                json={"step": 4},
            )
            assert r2.status_code == 200
            assert r2.json()["onboarding_step"] == 4
            assert r2.json()["is_onboarding_finished"] is True
    finally:
        try:
            del app.dependency_overrides[get_db]
        except Exception:
            pass


def test_onboarding_step1_auto_completes_on_successful_rewrite():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    db.add(Plan(name="Free", monthly_rewrite_limit=10, max_request_rate=60, billing_cycle_type="lifetime"))
    db.commit()
    free = db.query(Plan).filter(Plan.name == "Free").first()
    assert free is not None

    db.add(User(username="auto-step-shop.myshopify.com", email=None, plan_id=free.id))
    db.add(
        Shop(
            domain="auto-step-shop.myshopify.com",
            access_token="x",
            is_active=True,
            onboarding_step=0,
            is_onboarding_finished=False,
        )
    )
    db.commit()

    shop = record_successful_rewrite(db, "auto-step-shop.myshopify.com", amount=1)
    assert shop is not None
    assert int(shop.onboarding_step or 0) >= 1

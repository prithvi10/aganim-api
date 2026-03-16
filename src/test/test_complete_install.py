import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.shared.db.database import Base, get_db
from src.ecommerce.api.main import app
from src.ecommerce.db.models import User, Plan, Shop, OutreachLog


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()

    plan = Plan(name="Free", monthly_rewrite_limit=10, product_limit=10, billing_cycle_type="lifetime", max_request_rate=10)
    db.add(plan)
    db.commit()

    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def test_client(db_session):
    def _override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_db, None)


class TestCompleteInstall:
    def test_skipped_when_no_shop_param(self, test_client):
        resp = test_client.post("/api/admin/complete-install")
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        assert resp.json()["reason"] == "no_shop"

    def test_skipped_when_user_not_found(self, test_client):
        resp = test_client.post("/api/admin/complete-install?shop=unknown.myshopify.com")
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        assert resp.json()["reason"] == "no_user"

    @patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email", return_value=None)
    def test_skipped_when_no_email_available(self, mock_fetch, test_client, db_session):
        plan = db_session.query(Plan).first()
        shop = Shop(domain="noemail.myshopify.com", access_token="tok")
        db_session.add(shop)
        user = User(username="noemail.myshopify.com", plan_id=plan.id)
        db_session.add(user)
        db_session.commit()

        resp = test_client.post("/api/admin/complete-install?shop=noemail.myshopify.com")
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"
        assert resp.json()["reason"] == "no_email"

    @patch("src.ecommerce.api.shopify.admin.send_email", new_callable=AsyncMock)
    @patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email", return_value="owner@shop.com")
    def test_backfills_email_and_sends_welcome(self, mock_fetch, mock_send, test_client, db_session):
        mock_send.return_value = {"MessageId": "test-123"}

        plan = db_session.query(Plan).first()
        shop = Shop(domain="new.myshopify.com", access_token="tok123")
        db_session.add(shop)
        user = User(username="new.myshopify.com", plan_id=plan.id)
        db_session.add(user)
        db_session.commit()

        resp = test_client.post("/api/admin/complete-install?shop=new.myshopify.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "sent"
        assert data["email"] == "owner@shop.com"

        db_session.refresh(user)
        assert user.email == "owner@shop.com"
        mock_send.assert_called_once()

        log = db_session.query(OutreachLog).filter_by(recipient_shop="new.myshopify.com").first()
        assert log is not None
        assert "welcome" in log.subject.lower()

    @patch("src.ecommerce.api.shopify.admin.send_email", new_callable=AsyncMock)
    def test_already_sent_skips_duplicate(self, mock_send, test_client, db_session):
        plan = db_session.query(Plan).first()
        shop = Shop(domain="dup.myshopify.com", access_token="tok")
        db_session.add(shop)
        user = User(username="dup.myshopify.com", email="dup@shop.com", plan_id=plan.id)
        db_session.add(user)
        log = OutreachLog(
            recipient_email="dup@shop.com",
            recipient_shop="dup.myshopify.com",
            subject="Welcome to CrossBorder Agent!",
            body="welcome",
            status="sent",
        )
        db_session.add(log)
        db_session.commit()

        resp = test_client.post("/api/admin/complete-install?shop=dup.myshopify.com")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_sent"
        mock_send.assert_not_called()

    @patch("src.ecommerce.api.shopify.admin.send_email", new_callable=AsyncMock)
    @patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email", return_value="shared@owner.com")
    def test_skips_email_when_another_user_already_has_it(self, mock_fetch, mock_send, test_client, db_session):
        """When another user row already owns the email, skip assignment to avoid UniqueViolation."""
        plan = db_session.query(Plan).first()

        # First shop already has the email
        shop1 = Shop(domain="shop1.myshopify.com", access_token="tok1")
        db_session.add(shop1)
        user1 = User(username="shop1.myshopify.com", email="shared@owner.com", plan_id=plan.id)
        db_session.add(user1)

        # Second shop owned by same person — no email yet
        shop2 = Shop(domain="shop2.myshopify.com", access_token="tok2")
        db_session.add(shop2)
        user2 = User(username="shop2.myshopify.com", plan_id=plan.id)
        db_session.add(user2)
        db_session.commit()

        resp = test_client.post("/api/admin/complete-install?shop=shop2.myshopify.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        assert data["reason"] == "no_email"

        db_session.refresh(user2)
        assert user2.email is None
        mock_send.assert_not_called()

    @patch("src.ecommerce.api.shopify.admin.send_email", new_callable=AsyncMock)
    def test_does_not_refetch_if_email_already_present(self, mock_send, test_client, db_session):
        mock_send.return_value = {"MessageId": "test-456"}

        plan = db_session.query(Plan).first()
        shop = Shop(domain="exists.myshopify.com", access_token="tok")
        db_session.add(shop)
        user = User(username="exists.myshopify.com", email="existing@shop.com", plan_id=plan.id)
        db_session.add(user)
        db_session.commit()

        with patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email") as mock_fetch:
            resp = test_client.post("/api/admin/complete-install?shop=exists.myshopify.com")
            assert resp.status_code == 200
            assert resp.json()["status"] == "sent"
            mock_fetch.assert_not_called()

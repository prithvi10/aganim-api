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


class TestCompleteInstallEndpoint:
    """The endpoint now returns 204 immediately and delegates to a background task."""

    def test_returns_204_when_no_shop_param(self, test_client):
        resp = test_client.post("/api/admin/complete-install")
        assert resp.status_code == 204

    def test_returns_204_when_user_not_found(self, test_client):
        resp = test_client.post("/api/admin/complete-install?shop=unknown.myshopify.com")
        assert resp.status_code == 204

    def test_returns_204_for_valid_shop(self, test_client, db_session):
        plan = db_session.query(Plan).first()
        shop = Shop(domain="valid.myshopify.com", access_token="tok")
        db_session.add(shop)
        user = User(username="valid.myshopify.com", plan_id=plan.id)
        db_session.add(user)
        db_session.commit()

        with patch("src.ecommerce.api.shopify.admin._complete_install_sync"):
            resp = test_client.post("/api/admin/complete-install?shop=valid.myshopify.com")
        assert resp.status_code == 204


class TestCompleteInstallBackgroundTask:
    """Test _complete_install_sync which runs as a background task.

    We patch SessionLocal to return the test DB session so the
    background function operates on the same in-memory database.
    """

    def _make_session_factory(self, db_session):
        """Return a callable that mimics SessionLocal() but returns the test session.

        Wraps the real session so that .close() inside the background task
        doesn't actually close it, allowing post-call assertions to work.
        """
        class _NoCloseProxy:
            """Delegates everything to the real session except close()."""
            def __init__(self, real):
                self._real = real
            def close(self):
                pass
            def __getattr__(self, name):
                return getattr(self._real, name)

        proxy = _NoCloseProxy(db_session)
        return lambda: proxy

    @patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email", return_value=None)
    def test_skips_when_no_email_available(self, mock_fetch, db_session):
        from src.ecommerce.api.shopify.admin import _complete_install_sync

        plan = db_session.query(Plan).first()
        shop = Shop(domain="noemail.myshopify.com", access_token="tok")
        db_session.add(shop)
        user = User(username="noemail.myshopify.com", plan_id=plan.id)
        db_session.add(user)
        db_session.commit()

        with patch("src.ecommerce.api.shopify.admin.SessionLocal", self._make_session_factory(db_session)):
            _complete_install_sync("noemail.myshopify.com")

        db_session.refresh(user)
        assert user.email is None

    @patch("src.ecommerce.api.shopify.admin.send_email", new_callable=AsyncMock)
    @patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email", return_value="owner@shop.com")
    def test_backfills_email_and_sends_welcome(self, mock_fetch, mock_send, db_session):
        from src.ecommerce.api.shopify.admin import _complete_install_sync

        mock_send.return_value = {"MessageId": "test-123"}

        plan = db_session.query(Plan).first()
        shop = Shop(domain="new.myshopify.com", access_token="tok123")
        db_session.add(shop)
        user = User(username="new.myshopify.com", plan_id=plan.id)
        db_session.add(user)
        db_session.commit()

        with patch("src.ecommerce.api.shopify.admin.SessionLocal", self._make_session_factory(db_session)):
            _complete_install_sync("new.myshopify.com")

        db_session.refresh(user)
        assert user.email == "owner@shop.com"
        mock_send.assert_called_once()

        log = db_session.query(OutreachLog).filter_by(recipient_shop="new.myshopify.com").first()
        assert log is not None
        assert "welcome" in log.subject.lower()

    @patch("src.ecommerce.api.shopify.admin.send_email", new_callable=AsyncMock)
    def test_already_sent_skips_duplicate(self, mock_send, db_session):
        from src.ecommerce.api.shopify.admin import _complete_install_sync

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

        with patch("src.ecommerce.api.shopify.admin.SessionLocal", self._make_session_factory(db_session)):
            _complete_install_sync("dup.myshopify.com")

        mock_send.assert_not_called()

    @patch("src.ecommerce.api.shopify.admin.send_email", new_callable=AsyncMock)
    @patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email", return_value="shared@owner.com")
    def test_skips_email_when_another_user_already_has_it(self, mock_fetch, mock_send, db_session):
        """When another user row already owns the email, skip assignment to avoid UniqueViolation."""
        from src.ecommerce.api.shopify.admin import _complete_install_sync

        plan = db_session.query(Plan).first()
        shop1 = Shop(domain="shop1.myshopify.com", access_token="tok1")
        db_session.add(shop1)
        user1 = User(username="shop1.myshopify.com", email="shared@owner.com", plan_id=plan.id)
        db_session.add(user1)

        shop2 = Shop(domain="shop2.myshopify.com", access_token="tok2")
        db_session.add(shop2)
        user2 = User(username="shop2.myshopify.com", plan_id=plan.id)
        db_session.add(user2)
        db_session.commit()

        with patch("src.ecommerce.api.shopify.admin.SessionLocal", self._make_session_factory(db_session)):
            _complete_install_sync("shop2.myshopify.com")

        db_session.refresh(user2)
        assert user2.email is None
        mock_send.assert_not_called()

    @patch("src.ecommerce.api.shopify.admin.send_email", new_callable=AsyncMock)
    def test_does_not_refetch_if_email_already_present(self, mock_send, db_session):
        from src.ecommerce.api.shopify.admin import _complete_install_sync

        mock_send.return_value = {"MessageId": "test-456"}

        plan = db_session.query(Plan).first()
        shop = Shop(domain="exists.myshopify.com", access_token="tok")
        db_session.add(shop)
        user = User(username="exists.myshopify.com", email="existing@shop.com", plan_id=plan.id)
        db_session.add(user)
        db_session.commit()

        with patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email") as mock_fetch, \
             patch("src.ecommerce.api.shopify.admin.SessionLocal", self._make_session_factory(db_session)):
            _complete_install_sync("exists.myshopify.com")
            mock_fetch.assert_not_called()

    def test_skips_when_user_not_found(self, db_session):
        from src.ecommerce.api.shopify.admin import _complete_install_sync

        with patch("src.ecommerce.api.shopify.admin.SessionLocal", self._make_session_factory(db_session)):
            _complete_install_sync("unknown.myshopify.com")

    @patch("src.ecommerce.api.shopify.admin._fetch_shop_owner_email")
    def test_re_reads_token_on_each_retry(self, mock_fetch, db_session):
        """Verify the background task re-reads the access token before each retry."""
        from src.ecommerce.api.shopify.admin import _complete_install_sync

        mock_fetch.return_value = None

        plan = db_session.query(Plan).first()
        shop = Shop(domain="race.myshopify.com", access_token="tok-v1")
        db_session.add(shop)
        user = User(username="race.myshopify.com", plan_id=plan.id)
        db_session.add(user)
        db_session.commit()

        with patch("src.ecommerce.api.shopify.admin.SessionLocal", self._make_session_factory(db_session)), \
             patch("src.ecommerce.api.shopify.admin.get_shop_access_token") as mock_get_tok, \
             patch("time.sleep"):
            mock_get_tok.return_value = "tok-v1"
            _complete_install_sync("race.myshopify.com")

            # Initial call + 2 retries = 3 calls to get_shop_access_token
            assert mock_get_tok.call_count == 3

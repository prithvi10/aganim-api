import json
import hashlib
import hmac
import pytest
import respx
import httpx
from unittest.mock import patch
from fastapi.testclient import TestClient
from urllib.parse import urlencode, quote
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.main.api.main import app
from src.main.db.database import get_db, Base

# Setup In-Memory DB
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="module")
def db_engine():
    # Create tables
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    del app.dependency_overrides[get_db]

MOCK_INTEGRATION_SECRET = "test_integration_secret"
MOCK_INTEGRATION_KEY = "test_integration_key"

def generate_hmac(secret, params):
    # Sort and encode
    # Note: query string encoding in tests must match Shopify's standard
    # urlencode sorts keys, which is what we need
    sorted_params = urlencode(sorted(params.items()))
    digest = hmac.new(
        secret.encode('utf-8'),
        sorted_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return digest

@respx.mock
def test_integration_oauth_handshake(client): # Inject client fixture
    """
    End-to-End Integration Test for OAuth Handshake:
    1. Client (Shopify) hits /api/auth/callback with valid code & HMAC.
    2. API validates HMAC.
    3. API calls Shopify to exchange code for token.
    4. API returns success.
    """
    
    shop_domain = "integration-store.myshopify.com"
    auth_code = "auth_code_integration_123"
    
    # 1. Setup Request Params
    params = {
        "shop": shop_domain,
        "code": auth_code,
        "timestamp": "1600000000",
        "state": "nonce_integration",
        "host": "base64encodedhost"
    }
    # Calculate HMAC
    params["hmac"] = generate_hmac(MOCK_INTEGRATION_SECRET, params)

    # 2. Mock Shopify Token Exchange (External API)
    token_url = f"https://{shop_domain}/admin/oauth/access_token"
    mock_token_response = {
        "access_token": "shpat_integration_token",
        "scope": "write_products,read_orders"
    }
    
    mock_shopify = respx.post(token_url).mock(
        return_value=httpx.Response(200, json=mock_token_response)
    )

    # 3. Execute Request with Patched Secrets
    # We need to patch the secrets in both security (for validation) and controller (for exchange)
    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_INTEGRATION_SECRET), \
         patch("src.main.api.controller.SHOPIFY_API_KEY", MOCK_INTEGRATION_KEY), \
         patch("src.main.api.controller.SHOPIFY_API_SECRET", MOCK_INTEGRATION_SECRET), \
         patch("src.main.api.controller.SHOPIFY_UI_URL", "https://ui.test.com"):
        
        response = client.get("/api/auth/callback", params=params, follow_redirects=False)
        
        # 4. Verifications
        assert response.status_code == 307
        assert response.headers["location"].startswith("https://ui.test.com/auth/login")
        assert shop_domain in response.headers["location"]
        
        # Verify Shopify API was called correctly
        assert mock_shopify.called
        request_body = json.loads(mock_shopify.calls.last.request.content)
        assert request_body["client_id"] == MOCK_INTEGRATION_KEY
        assert request_body["client_secret"] == MOCK_INTEGRATION_SECRET
        assert request_body["code"] == auth_code

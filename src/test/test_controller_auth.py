import pytest
import hmac
import hashlib
import respx
import httpx
from httpx import Response
from urllib.parse import urlencode
from fastapi.testclient import TestClient
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.main.api.main import app
from src.main.db.database import get_db, Base

# Mock Config
MOCK_API_KEY = "test_api_key"
MOCK_API_SECRET = "test_api_secret"

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

def generate_hmac(secret, params):
    sorted_params = urlencode(sorted(params.items()))
    digest = hmac.new(
        secret.encode('utf-8'),
        sorted_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return digest

@pytest.fixture
def auth_params():
    return {
        "shop": "test-store.myshopify.com",
        "code": "auth_code_123",
        "timestamp": "1600000000"
    }

@respx.mock
def test_auth_callback_success(client, auth_params): # Injected client fixture
    """
    Test successful OAuth callback flow:
    1. Verify HMAC (Middleware/Security check).
    2. Exchange code for token (External API call).
    3. Return success response.
    """
    
    # 1. Prepare Request with HMAC
    params = auth_params.copy()
    params["hmac"] = generate_hmac(MOCK_API_SECRET, params)
    
    # 2. Mock Shopify Token Exchange Endpoint
    token_url = f"https://{auth_params['shop']}/admin/oauth/access_token"
    mock_route = respx.post(token_url).mock(
        return_value=Response(200, json={"access_token": "shpat_123456", "scope": "write_products"})
    )
    
    # 3. Execute Request
    with patch("src.main.api.controller.SHOPIFY_API_KEY", MOCK_API_KEY), \
         patch("src.main.api.controller.SHOPIFY_API_SECRET", MOCK_API_SECRET), \
         patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_API_SECRET):
        
        response = client.get("/api/auth/callback", params=params)
        
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["shop"] == auth_params["shop"]
        
        # Verify Token Exchange call was made with correct params
        assert mock_route.called
        request = mock_route.calls.last.request
        import json
        body = json.loads(request.content)
        assert body["client_id"] == MOCK_API_KEY
        assert body["client_secret"] == MOCK_API_SECRET
        assert body["code"] == auth_params["code"]

def test_auth_callback_invalid_hmac(client, auth_params):
    """Test callback fails with 400 if HMAC is invalid."""
    params = auth_params.copy()
    params["hmac"] = "invalid_signature"
    
    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_API_SECRET):
        response = client.get("/api/auth/callback", params=params)
        
        assert response.status_code == 400
        assert "Invalid HMAC signature" in response.json()["detail"]

def test_auth_callback_missing_params(client, auth_params):
    """Test callback fails if required params (code/shop) are missing (even if HMAC valid)."""
    # Note: If 'code' is missing from params BEFORE hmac calc, the calc is valid for THAT set.
    # But the controller checks for code/shop explicitly.
    
    incomplete_params = {"shop": "test.myshopify.com", "timestamp": "123"}
    incomplete_params["hmac"] = generate_hmac(MOCK_API_SECRET, incomplete_params)

    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_API_SECRET):
        response = client.get("/api/auth/callback", params=incomplete_params)
        
        # Controller check for missing code
        assert response.status_code == 400
        assert "Missing code" in response.json()["detail"]

@respx.mock
def test_auth_callback_exchange_failure(client, auth_params):
    """Test callback handles failure from Shopify Token API."""
    params = auth_params.copy()
    params["hmac"] = generate_hmac(MOCK_API_SECRET, params)
    
    # Mock Shopify API returning error (e.g., invalid code)
    token_url = f"https://{auth_params['shop']}/admin/oauth/access_token"
    respx.post(token_url).mock(return_value=Response(400, json={"error": "invalid_request"}))
    
    with patch("src.main.api.controller.SHOPIFY_API_KEY", MOCK_API_KEY), \
         patch("src.main.api.controller.SHOPIFY_API_SECRET", MOCK_API_SECRET), \
         patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_API_SECRET):
        
        response = client.get("/api/auth/callback", params=params)
        
        assert response.status_code == 400
        assert "Failed to exchange access token" in response.json()["detail"]

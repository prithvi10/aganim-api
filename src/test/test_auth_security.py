import pytest
import hmac
import hashlib
from urllib.parse import urlencode
from fastapi import HTTPException, Request
from unittest.mock import patch, MagicMock
from src.main.security.security import verify_shopify_redirect, verify_shopify_proxy_request

# Mock Secret
MOCK_SECRET = "test_secret_key"

@pytest.fixture
def valid_params():
    return {
        "shop": "test-store.myshopify.com",
        "code": "1234567890",
        "timestamp": "123456789",
        "state": "nonce123"
    }

def generate_hmac(secret, params):
    # Sort and encode
    # Note: query_params might contain list values in some frameworks, but here we assume flat
    sorted_params = urlencode(sorted(params.items()))
    digest = hmac.new(
        secret.encode('utf-8'),
        sorted_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return digest

def generate_proxy_signature(secret, params):
    # 1. Remove signature if present
    params_to_sign = params.copy()
    if "signature" in params_to_sign:
        del params_to_sign["signature"]
        
    # 2. Sort and Encode (using & separator as per security.py implementation)
    sorted_items = sorted(params_to_sign.items())
    canonical_string = urlencode(sorted_items)
    
    # 3. Sign
    digest = hmac.new(
        secret.encode('utf-8'),
        canonical_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return digest

# --- verify_shopify_redirect Tests (Synchronous) ---

def test_verify_shopify_redirect_success(valid_params):
    """Test valid HMAC verification."""
    # Generate valid HMAC
    valid_hmac = generate_hmac(MOCK_SECRET, valid_params)
    params = valid_params.copy()
    params["hmac"] = valid_hmac
    
    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SECRET):
        assert verify_shopify_redirect(params) is True

def test_verify_shopify_redirect_missing_hmac(valid_params):
    """Test failure when HMAC param is missing."""
    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SECRET):
        with pytest.raises(HTTPException) as exc_info:
            verify_shopify_redirect(valid_params)
        
        assert exc_info.value.status_code == 400
        assert "Missing HMAC parameter" in exc_info.value.detail

def test_verify_shopify_redirect_invalid_signature(valid_params):
    """Test failure when HMAC signature is incorrect."""
    params = valid_params.copy()
    params["hmac"] = "invalid_hash_value"
    
    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SECRET):
        with pytest.raises(HTTPException) as exc_info:
            verify_shopify_redirect(params)
        
        assert exc_info.value.status_code == 400
        assert "Invalid HMAC signature" in exc_info.value.detail

def test_verify_shopify_redirect_missing_config():
    """Test failure when Server Config is missing."""
    with patch("src.main.security.security.SHOPIFY_API_SECRET", None):
        with pytest.raises(HTTPException) as exc_info:
            verify_shopify_redirect({"hmac": "123"})
        
        assert exc_info.value.status_code == 500
        assert "Server Configuration Error" in exc_info.value.detail

# --- verify_shopify_proxy_request Tests (Async) ---

@pytest.fixture
def valid_proxy_params():
    return {
        "shop": "test-store.myshopify.com",
        "path_prefix": "/apps/proxy",
        "timestamp": "123456789",
        "logged_in_customer_id": "123"
    }

@pytest.mark.asyncio
async def test_verify_shopify_proxy_success(valid_proxy_params):
    """Test valid App Proxy signature verification."""
    valid_signature = generate_proxy_signature(MOCK_SECRET, valid_proxy_params)
    params = valid_proxy_params.copy()
    params["signature"] = valid_signature
    
    # Mock Request
    mock_request = MagicMock(spec=Request)
    mock_request.query_params = params
    
    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SECRET):
        result = await verify_shopify_proxy_request(mock_request)
        assert result == valid_proxy_params["shop"]

@pytest.mark.asyncio
async def test_verify_shopify_proxy_missing_signature(valid_proxy_params):
    """Test failure when signature param is missing."""
    # Mock Request
    mock_request = MagicMock(spec=Request)
    mock_request.query_params = valid_proxy_params # No signature
    
    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SECRET):
        with pytest.raises(HTTPException) as exc_info:
            await verify_shopify_proxy_request(mock_request)
        
        assert exc_info.value.status_code == 400
        assert "Missing signature parameter" in exc_info.value.detail

@pytest.mark.asyncio
async def test_verify_shopify_proxy_invalid_signature(valid_proxy_params):
    """Test failure when signature is incorrect."""
    params = valid_proxy_params.copy()
    params["signature"] = "invalid_signature"
    
    # Mock Request
    mock_request = MagicMock(spec=Request)
    mock_request.query_params = params
    
    with patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SECRET):
        with pytest.raises(HTTPException) as exc_info:
            await verify_shopify_proxy_request(mock_request)
        
        assert exc_info.value.status_code == 401
        assert "Invalid signature" in exc_info.value.detail

@pytest.mark.asyncio
async def test_verify_shopify_proxy_missing_config(valid_proxy_params):
    """Test failure when secret is missing."""
    params = valid_proxy_params.copy()
    params["signature"] = "something"
    
    mock_request = MagicMock(spec=Request)
    mock_request.query_params = params

    with patch("src.main.security.security.SHOPIFY_API_SECRET", None):
        with pytest.raises(HTTPException) as exc_info:
            await verify_shopify_proxy_request(mock_request)
        
        assert exc_info.value.status_code == 500
        assert "Server Configuration Error" in exc_info.value.detail

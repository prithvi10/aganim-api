import pytest
import hmac
import hashlib
from urllib.parse import urlencode
from fastapi import HTTPException
from unittest.mock import patch
from src.main.security.security import verify_shopify_redirect

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
    sorted_params = urlencode(sorted(params.items()))
    digest = hmac.new(
        secret.encode('utf-8'),
        sorted_params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return digest

def test_verify_shopify_redirect_success(valid_params):
    """Test valid HMAC verification."""
    # Generate valid HMAC
    valid_hmac = generate_hmac(MOCK_SECRET, valid_params)
    params = valid_params.copy()
    params["hmac"] = valid_hmac
    
    from unittest.mock import patch
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


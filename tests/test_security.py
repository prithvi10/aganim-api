import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock
import jwt
import os
import security
from security import verify_shopify_session

# Mock Environment Variables
@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("SHOPIFY_API_SECRET", "test_secret")
    monkeypatch.setenv("SHOPIFY_API_KEY", "test_api_key")
    # Also update the module-level constants since they are loaded at import time
    monkeypatch.setattr(security, "SHOPIFY_API_SECRET", "test_secret")
    monkeypatch.setattr(security, "SHOPIFY_API_KEY", "test_api_key")

def test_verify_session_success(mock_env):
    """Test successful session verification."""
    valid_token = "valid_token"
    expected_shop = "test-shop.myshopify.com"
    
    # Create a mock payload that jwt.decode would return
    mock_payload = {"dest": f"https://{expected_shop}"}
    
    with patch("jwt.decode", return_value=mock_payload) as mock_jwt:
        result = verify_shopify_session(authorization=f"Bearer {valid_token}")
        
        assert result == expected_shop
        mock_jwt.assert_called_once()

def test_verify_session_missing_config(monkeypatch):
    """Test error when API credentials are missing."""
    # We must patch the module-level variables directly
    monkeypatch.setattr(security, "SHOPIFY_API_SECRET", None)
    
    with pytest.raises(HTTPException) as exc:
        verify_shopify_session(authorization="Bearer token")
    assert exc.value.status_code == 500
    assert "Server Misconfiguration" in exc.value.detail

def test_verify_session_invalid_header_format(mock_env):
    """Test error when header format is invalid."""
    with pytest.raises(HTTPException) as exc:
        verify_shopify_session(authorization="InvalidToken")
    assert exc.value.status_code == 401
    assert "Invalid authorization header format" in exc.value.detail

def test_verify_session_missing_dest(mock_env):
    """Test error when token payload is missing 'dest'."""
    with patch("jwt.decode", return_value={}):
        with pytest.raises(HTTPException) as exc:
            verify_shopify_session(authorization="Bearer token")
        assert exc.value.status_code == 401
        assert "missing 'dest'" in exc.value.detail

def test_verify_session_expired_token(mock_env):
    """Test error when token is expired."""
    with patch("jwt.decode", side_effect=jwt.ExpiredSignatureError):
        with pytest.raises(HTTPException) as exc:
            verify_shopify_session(authorization="Bearer token")
        assert exc.value.status_code == 401
        assert "Token has expired" in exc.value.detail

def test_verify_session_invalid_token(mock_env):
    """Test error when token is invalid."""
    with patch("jwt.decode", side_effect=jwt.InvalidTokenError):
        with pytest.raises(HTTPException) as exc:
            verify_shopify_session(authorization="Bearer token")
        assert exc.value.status_code == 401
        assert "Invalid Shopify Token" in exc.value.detail

def test_verify_session_unknown_error(mock_env):
    """Test handling of unexpected errors."""
    with patch("jwt.decode", side_effect=Exception("Boom")):
        with pytest.raises(HTTPException) as exc:
            verify_shopify_session(authorization="Bearer token")
        assert exc.value.status_code == 500
        assert "Internal Authentication Error" in exc.value.detail

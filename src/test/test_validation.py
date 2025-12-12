import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.main.api.validation import validate_api_key_and_quota, validate_rewrite_request, validate_shop_and_quota
from src.main.db.db_models import User, Plan

# --- Tests for validate_api_key_and_quota ---

@patch("src.main.api.validation.get_user_quota_context")
def test_validate_api_key_valid(mock_get_context):
    """Test successful validation."""
    mock_db = MagicMock(spec=Session)
    key_hash = "valid_hash"
    
    # Mock context returned from DB transaction
    mock_user = MagicMock(spec=User)
    mock_user.username = "test_user"
    mock_plan = MagicMock(spec=Plan)
    mock_plan.monthly_token_quota = 1000
    
    mock_context = {
        "user": mock_user,
        "plan": mock_plan,
        "api_key_id": 1,
        "billing_cycle_start": "2023-01-01",
        "current_usage": 500,
        "is_active": True
    }
    mock_get_context.return_value = mock_context
    
    result = validate_api_key_and_quota(mock_db, key_hash)
    
    assert result == mock_context
    mock_get_context.assert_called_once_with(mock_db, key_hash)

def test_validate_api_key_missing():
    """Test validation with empty key hash."""
    mock_db = MagicMock(spec=Session)
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, "")
    assert exc.value.status_code == 401
    assert "Missing API Key" in exc.value.detail

@patch("src.main.api.validation.get_user_quota_context")
def test_validate_api_key_invalid_hash(mock_get_context):
    """Test validation when key lookup returns None."""
    mock_db = MagicMock(spec=Session)
    mock_get_context.return_value = None
    
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, "invalid_hash")
    assert exc.value.status_code == 401
    assert "Invalid API Key" in exc.value.detail

@patch("src.main.api.validation.get_user_quota_context")
def test_validate_api_key_inactive(mock_get_context):
    """Test validation when key is inactive."""
    mock_db = MagicMock(spec=Session)
    
    mock_context = {
        "user": MagicMock(spec=User),
        "plan": MagicMock(spec=Plan),
        "current_usage": 0,
        "is_active": False
    }
    mock_get_context.return_value = mock_context
    
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, "inactive_hash")
    assert exc.value.status_code == 401
    assert "Inactive API Key" in exc.value.detail

@patch("src.main.api.validation.get_user_quota_context")
def test_validate_api_key_quota_exceeded(mock_get_context):
    """Test validation when quota is exceeded."""
    mock_db = MagicMock(spec=Session)
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.monthly_token_quota = 100
    
    mock_context = {
        "user": MagicMock(username="heavy_user"),
        "plan": mock_plan,
        "current_usage": 150, # Exceeds 100
        "is_active": True
    }
    mock_get_context.return_value = mock_context
    
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, "quota_hash")
    assert exc.value.status_code == 429
    assert "Monthly token quota exceeded" in exc.value.detail

# --- Tests for validate_rewrite_request ---

def test_validate_rewrite_request_valid():
    """Test valid request body."""
    body = {"japanese_description": "Valid description"}
    # Should not raise exception
    validate_rewrite_request(body)

def test_validate_rewrite_request_empty():
    """Test empty description."""
    body = {"japanese_description": ""}
    with pytest.raises(HTTPException) as exc:
        validate_rewrite_request(body)
    assert exc.value.status_code == 422
    assert "Japanese description cannot be empty" in exc.value.detail

def test_validate_rewrite_request_whitespace():
    """Test whitespace-only description."""
    body = {"japanese_description": "   "}
    with pytest.raises(HTTPException) as exc:
        validate_rewrite_request(body)
    assert exc.value.status_code == 422

def test_validate_rewrite_request_too_long():
    """Test description exceeding length limit."""
    long_desc = "a" * 5001
    body = {"japanese_description": long_desc}
    with pytest.raises(HTTPException) as exc:
        validate_rewrite_request(body)
    assert exc.value.status_code == 422
    assert "Description too long" in exc.value.detail

# --- Tests for validate_shop_and_quota ---

@patch("src.main.api.validation.get_shop_quota_context")
def test_validate_shop_valid(mock_get_context):
    """Test successful shop validation."""
    mock_db = MagicMock(spec=Session)
    shop_domain = "valid-shop.myshopify.com"
    
    mock_user = MagicMock(spec=User)
    mock_user.username = shop_domain
    mock_plan = MagicMock(spec=Plan)
    mock_plan.monthly_token_quota = 1000
    
    mock_context = {
        "user": mock_user,
        "plan": mock_plan,
        "api_key_id": 1,
        "billing_cycle_start": "2023-01-01",
        "current_usage": 500,
        "is_active": True
    }
    mock_get_context.return_value = mock_context
    
    result = validate_shop_and_quota(mock_db, shop_domain)
    assert result == mock_context

def test_validate_shop_missing_domain():
    """Test validation with empty shop domain."""
    mock_db = MagicMock(spec=Session)
    with pytest.raises(HTTPException) as exc:
        validate_shop_and_quota(mock_db, "")
    assert exc.value.status_code == 401
    assert "Missing Shop Domain" in exc.value.detail

@patch("src.main.api.validation.get_shop_quota_context")
def test_validate_shop_invalid(mock_get_context):
    """Test validation when shop lookup returns None."""
    mock_db = MagicMock(spec=Session)
    mock_get_context.return_value = None
    
    with pytest.raises(HTTPException) as exc:
        validate_shop_and_quota(mock_db, "invalid-shop")
    assert exc.value.status_code == 401
    assert "Invalid Shop or No Active API Key" in exc.value.detail

@patch("src.main.api.validation.get_shop_quota_context")
def test_validate_shop_quota_exceeded(mock_get_context):
    """Test validation when shop quota is exceeded."""
    mock_db = MagicMock(spec=Session)
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.monthly_token_quota = 100
    
    mock_context = {
        "user": MagicMock(username="heavy_shop"),
        "plan": mock_plan,
        "current_usage": 150,
        "is_active": True
    }
    mock_get_context.return_value = mock_context
    
    with pytest.raises(HTTPException) as exc:
        validate_shop_and_quota(mock_db, "heavy_shop")
    assert exc.value.status_code == 429
    assert "Monthly token quota exceeded" in exc.value.detail

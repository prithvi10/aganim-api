import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.main.api.validation import validate_api_key_and_quota, validate_rewrite_request, validate_shop_and_quota
from src.main.db.db_models import User, Plan, Shop

# --- Tests for validate_api_key_and_quota ---

def test_validate_api_key_valid():
    """Test deprecated endpoint returns 410."""
    mock_db = MagicMock(spec=Session)
    key_hash = "valid_hash"
    
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, key_hash)
    assert exc.value.status_code == 410
    assert "deprecated" in exc.value.detail

def test_validate_api_key_missing():
    """Test validation with empty key hash."""
    mock_db = MagicMock(spec=Session)
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, "")
    assert exc.value.status_code == 410
    assert "deprecated" in exc.value.detail

def test_validate_api_key_invalid_hash():
    """Test validation when key lookup returns None."""
    mock_db = MagicMock(spec=Session)
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, "invalid_hash")
    assert exc.value.status_code == 410
    assert "deprecated" in exc.value.detail

def test_validate_api_key_inactive():
    """Test validation when key is inactive."""
    mock_db = MagicMock(spec=Session)
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, "inactive_hash")
    assert exc.value.status_code == 410
    assert "deprecated" in exc.value.detail

def test_validate_api_key_quota_exceeded():
    """Test validation when quota is exceeded."""
    mock_db = MagicMock(spec=Session)
    with pytest.raises(HTTPException) as exc:
        validate_api_key_and_quota(mock_db, "quota_hash")
    assert exc.value.status_code == 410
    assert "deprecated" in exc.value.detail

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
    mock_plan.product_limit = 100

    mock_shop = MagicMock(spec=Shop)
    mock_shop.next_reset_date = None
    
    mock_context = {
        "user": mock_user,
        "plan": mock_plan,
        "shop": mock_shop,
        "rewrites_used": 10,
        "rewrite_limit": 100,
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
    # Updated error message expectation
    assert "Invalid Shop or User not found" in exc.value.detail

@patch("src.main.api.validation.get_shop_quota_context")
def test_validate_shop_quota_exceeded(mock_get_context):
    """Test validation when monthly rewrite limit is exceeded."""
    mock_db = MagicMock(spec=Session)
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.product_limit = 100

    mock_shop = MagicMock(spec=Shop)
    mock_shop.next_reset_date = None
    
    mock_context = {
        "user": MagicMock(username="heavy_shop"),
        "plan": mock_plan,
        "shop": mock_shop,
        "rewrites_used": 150,
        "rewrite_limit": 100,
        "is_active": True
    }
    mock_get_context.return_value = mock_context
    
    with pytest.raises(HTTPException) as exc:
        validate_shop_and_quota(mock_db, "heavy_shop")
    assert exc.value.status_code == 403
    assert "Monthly limit reached" in exc.value.detail


@patch("src.main.api.validation.get_shop_quota_context")
def test_validate_shop_free_lifetime_allows_when_remaining(mock_get_context):
    """Free/lifetime plan should allow when lifetime credits remain."""
    mock_db = MagicMock(spec=Session)
    mock_plan = MagicMock(spec=Plan)
    mock_plan.name = "Free"
    mock_plan.billing_cycle_type = "lifetime"
    mock_shop = MagicMock(spec=Shop)

    mock_get_context.return_value = {
        "user": MagicMock(username="free_shop"),
        "plan": mock_plan,
        "shop": mock_shop,
        "rewrites_used": 3,
        "rewrite_limit": 10,
        "billing_cycle_type": "lifetime",
        "lifetime_rewrites_remaining": 7,
        "is_active": True,
    }

    ctx = validate_shop_and_quota(mock_db, "free_shop", enforce_limit=True)
    assert ctx["billing_cycle_type"] == "lifetime"
    assert ctx["lifetime_rewrites_remaining"] == 7


@patch("src.main.api.validation.get_shop_quota_context")
def test_validate_shop_free_lifetime_blocks_when_zero_remaining(mock_get_context):
    """Free/lifetime plan should 403 when lifetime credits are exhausted."""
    mock_db = MagicMock(spec=Session)
    mock_plan = MagicMock(spec=Plan)
    mock_plan.name = "Free"
    mock_plan.billing_cycle_type = "lifetime"
    mock_shop = MagicMock(spec=Shop)

    mock_get_context.return_value = {
        "user": MagicMock(username="free_shop"),
        "plan": mock_plan,
        "shop": mock_shop,
        "rewrites_used": 10,
        "rewrite_limit": 10,
        "billing_cycle_type": "lifetime",
        "lifetime_rewrites_remaining": 0,
        "is_active": True,
    }

    with pytest.raises(HTTPException) as exc:
        validate_shop_and_quota(mock_db, "free_shop", enforce_limit=True)
    assert exc.value.status_code == 403
    assert "free lifetime credits" in str(exc.value.detail).lower()


@patch("src.main.api.validation.get_shop_quota_context")
def test_validate_shop_expired_paid_blocks_with_403(mock_get_context):
    """Returning paid user with expired prepaid window must re-purchase (no fallback to Free)."""
    mock_db = MagicMock(spec=Session)
    mock_plan = MagicMock(spec=Plan)
    mock_plan.name = "Free"
    mock_plan.billing_cycle_type = "lifetime"
    mock_shop = MagicMock(spec=Shop)

    mock_get_context.return_value = {
        "user": MagicMock(username="paid_then_uninstalled"),
        "plan": mock_plan,
        "shop": mock_shop,
        "rewrites_used": 0,
        "rewrite_limit": 0,
        "billing_cycle_type": "recurring",
        "expired_paid": True,
        "is_active": True,
    }

    with pytest.raises(HTTPException) as exc:
        validate_shop_and_quota(mock_db, "paid_then_uninstalled", enforce_limit=True)
    assert exc.value.status_code == 403
    assert "pre-paid period has ended" in str(exc.value.detail).lower()

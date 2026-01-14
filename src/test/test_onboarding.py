import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.main.service.onboarding import onboard_user
from src.main.api.models import OnboardingRequest, OnboardingResponse
from src.main.db.db_models import User, Plan

@pytest.fixture
def mock_db_session():
    return MagicMock(spec=Session)

@pytest.fixture
def valid_request():
    return OnboardingRequest(
        username="test-shop.myshopify.com",
        email="test@example.com",
        plan_id=1
    )

@pytest.fixture
def mock_plan():
    plan = MagicMock(spec=Plan)
    plan.id = 1
    plan.name = "Basic"
    return plan

@pytest.fixture
def mock_user(mock_plan):
    user = MagicMock(spec=User)
    user.id = 123
    user.username = "test-shop.myshopify.com"
    user.email = "test@example.com"
    user.plan_id = mock_plan.id
    user.plan = mock_plan
    return user

def test_onboard_user_success(mock_db_session, valid_request, mock_plan, mock_user):
    """Test successful user onboarding."""
    
    # Mock DB transactions
    with patch("src.main.service.onboarding.db_transactions.get_plan_by_id", return_value=mock_plan) as mock_get_plan, \
         patch("src.main.service.onboarding.db_transactions.get_user_by_username", return_value=None) as mock_get_user, \
         patch("src.main.service.onboarding.db_transactions.create_user", return_value=mock_user) as mock_create_user:

        response = onboard_user(mock_db_session, valid_request)

        # Verify response
        assert isinstance(response, OnboardingResponse)
        assert response.user_id == 123
        assert response.username == "test-shop.myshopify.com"
        assert response.plan_name == "Basic"
        # API Key is deprecated but returned as placeholder
        assert response.api_key == "deprecated"

        # Verify DB calls
        mock_get_plan.assert_called_once_with(mock_db_session, 1)
        mock_get_user.assert_called_once_with(mock_db_session, "test-shop.myshopify.com")
        mock_create_user.assert_called_once_with(
            db=mock_db_session,
            username="test-shop.myshopify.com",
            email="test@example.com",
            plan_id=1
        )

def test_onboard_user_plan_not_found(mock_db_session, valid_request):
    """Test onboarding fails when plan ID is invalid."""
    with patch("src.main.service.onboarding.db_transactions.get_plan_by_id", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            onboard_user(mock_db_session, valid_request)
        
        assert exc_info.value.status_code == 400
        assert "Invalid Plan ID" in exc_info.value.detail

def test_onboard_user_already_exists(mock_db_session, valid_request, mock_plan, mock_user):
    """Test onboarding fails when user already exists."""
    with patch("src.main.service.onboarding.db_transactions.get_plan_by_id", return_value=mock_plan), \
         patch("src.main.service.onboarding.db_transactions.get_user_by_username", return_value=mock_user):
        
        with pytest.raises(HTTPException) as exc_info:
            onboard_user(mock_db_session, valid_request)
        
        assert exc_info.value.status_code == 409
        assert "User already exists" in exc_info.value.detail

def test_onboard_user_creation_failure(mock_db_session, valid_request, mock_plan):
    """Test onboarding handles DB error during user creation."""
    with patch("src.main.service.onboarding.db_transactions.get_plan_by_id", return_value=mock_plan), \
         patch("src.main.service.onboarding.db_transactions.get_user_by_username", return_value=None), \
         patch("src.main.service.onboarding.db_transactions.create_user", side_effect=Exception("DB Error")):
        
        with pytest.raises(HTTPException) as exc_info:
            onboard_user(mock_db_session, valid_request)
        
        assert exc_info.value.status_code == 500
        assert "Failed to create user record" in exc_info.value.detail


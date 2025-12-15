import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session
from datetime import date

from src.main.api.main import app
from src.main.security.security import get_api_key_hash, verify_shopify_proxy_request
from src.main.db.database import get_db
from src.main.db.db_models import User, Plan

# Initialize Test Client
client = TestClient(app)

# Mock the security dependency (API Key Hash)
def mock_get_api_key_hash():
    return "mocked_key_hash"

# Mock the DB session
def mock_get_db():
    db = MagicMock(spec=Session)
    return db

# Override the dependencies globally
app.dependency_overrides[get_api_key_hash] = mock_get_api_key_hash
app.dependency_overrides[get_db] = mock_get_db

@pytest.fixture
def mock_auth_context():
    mock_user = MagicMock(spec=User)
    mock_user.username = "test-shop.myshopify.com"
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    
    return {
        "user": mock_user,
        "plan": mock_plan,
        "api_key_id": 1,
        "billing_cycle_start": date(2023, 1, 1),
        "current_usage": 0
    }

def test_generate_copy_endpoint_success(mock_auth_context):
    """Test the API endpoint success path."""
    mock_response_text = "Generated English Copy"
    mock_openai_response = MagicMock()
    mock_openai_response.choices = [MagicMock(message=MagicMock(content=mock_response_text))]
    mock_openai_response.usage.total_tokens = 10

    # Patch the validation function
    with patch("src.main.api.controller.validate_api_key_and_quota", return_value=mock_auth_context) as mock_validate:
        # Patch the update usage function
        with patch("src.main.api.controller.update_token_usage") as mock_update:
            # Patch the OpenAI service instance
            with patch("src.main.api.controller.openai_service.generate_copy", return_value=mock_openai_response) as mock_generate:
                
                response = client.post(
                    "/api/generate-copy",
                    json={
                        "product_name": "Test Product",
                        "japanese_description": "Test Description",
                        "category": "Test Category"
                    }
                )

                assert response.status_code == 200
                assert response.json() == {
                    "status": "success",
                    "english_copy": mock_response_text
                }
                
                mock_validate.assert_called_once()
                mock_generate.assert_called_once()
                mock_update.assert_called_once()

def test_generate_copy_endpoint_service_error(mock_auth_context):
    """Test the API endpoint when service raises an exception."""
    with patch("src.main.api.controller.validate_api_key_and_quota", return_value=mock_auth_context):
        with patch("src.main.api.controller.openai_service.generate_copy", side_effect=Exception("Service Error")):
            response = client.post(
                "/api/generate-copy",
                json={
                    "product_name": "Test Product",
                    "japanese_description": "Test Description"
                }
            )
            
            assert response.status_code == 500
            assert "Service Error" in response.json()["detail"]

def test_generate_copy_validation_error():
    """Test API validation error (missing required field)."""
    response = client.post(
        "/api/generate-copy",
        json={
            "product_name": "Test Product"
            # Missing japanese_description
        }
    )
    assert response.status_code == 422

# --- NEW PROXY TESTS ---

def test_proxy_generate_copy_endpoint_success(mock_auth_context):
    """Test the Proxy API endpoint success path."""
    mock_response_text = "Generated English Copy"
    mock_openai_response = MagicMock()
    mock_openai_response.choices = [MagicMock(message=MagicMock(content=mock_response_text))]
    mock_openai_response.usage.total_tokens = 10

    # Mock the proxy signature verification dependency
    def mock_verify_proxy():
        return "test-shop.myshopify.com"
    
    app.dependency_overrides[verify_shopify_proxy_request] = mock_verify_proxy

    try:
        with patch("src.main.api.controller.validate_shop_and_quota", return_value=mock_auth_context) as mock_validate:
            with patch("src.main.api.controller.update_token_usage"):
                with patch("src.main.api.controller.openai_service.generate_copy", return_value=mock_openai_response):
                    
                    response = client.post(
                        "/api/proxy/generate-copy?shop=test-shop.myshopify.com&signature=valid",
                        json={
                            "product_name": "Proxy Product",
                            "japanese_description": "Proxy Desc",
                            "category": "Proxy Cat"
                        }
                    )

                    assert response.status_code == 200
                    assert response.json()["english_copy"] == mock_response_text
                    
                    mock_validate.assert_called_once()
                    args, _ = mock_validate.call_args
                    assert args[1] == "test-shop.myshopify.com" 
    finally:
        del app.dependency_overrides[verify_shopify_proxy_request]

def test_proxy_generate_copy_missing_signature():
    """Test proxy endpoint fails correctly when signature validation fails (dependency raises error)."""
    
    from fastapi import HTTPException
    
    # Mock the proxy signature verification dependency to fail
    def mock_verify_proxy_fail():
        raise HTTPException(status_code=401, detail="Invalid signature")
        
    app.dependency_overrides[verify_shopify_proxy_request] = mock_verify_proxy_fail

    try:
        response = client.post(
            "/api/proxy/generate-copy", 
            json={
                "product_name": "Proxy Product",
                "japanese_description": "Proxy Desc"
            }
        )
        assert response.status_code == 401
        assert "Invalid signature" in response.json()["detail"]
    finally:
        del app.dependency_overrides[verify_shopify_proxy_request]

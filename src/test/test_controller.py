import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app
from security import verify_shopify_session

# Initialize Test Client
client = TestClient(app)

# Mock the security dependency to bypass JWT verification
def mock_verify_session():
    return "test-shop.myshopify.com"

# Override the dependency
app.dependency_overrides[verify_shopify_session] = mock_verify_session

def test_generate_copy_endpoint_success():
    """Test the API endpoint success path."""
    mock_response_text = "Generated English Copy"
    
    # We need to patch the 'openai_service' instance used in 'controller.py'
    # Since 'controller.py' instantiates it at module level, we patch it there.
    with patch("controller.openai_service.generate_copy", return_value=mock_response_text) as mock_generate:
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
        
        mock_generate.assert_called_once_with(
            product_name="Test Product",
            category="Test Category",
            japanese_description="Test Description"
        )

def test_generate_copy_endpoint_service_error():
    """Test the API endpoint when service raises an exception."""
    with patch("controller.openai_service.generate_copy", side_effect=Exception("Service Error")):
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






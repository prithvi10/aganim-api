import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
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
    mock_user.id = 1 # Set user ID
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    
    return {
        "user": mock_user,
        "plan": mock_plan,
        "user_id": 1, # Changed from api_key_id
        "billing_cycle_start": date(2023, 1, 1),
        "current_usage": 0
    }

def test_generate_copy_endpoint_deprecated(mock_auth_context):
    """Test the API endpoint returns 410 Deprecated."""
    response = client.post(
        "/api/generate-copy",
        json={
            "product_name": "Test Product",
            "japanese_description": "Test Description",
            "category": "Test Category"
        }
    )
    assert response.status_code == 410
    assert "deprecated" in response.json()["detail"]

# --- NEW PROXY TESTS ---

def test_proxy_generate_copy_endpoint_success(mock_auth_context):
    """Test the Proxy API endpoint success path."""
    # Mock LLM returning JSON
    mock_response_text = '{"title": "My Title", "description": "My Description"}'
    mock_openai_response = MagicMock()
    mock_openai_response.choices = [MagicMock(message=MagicMock(content=mock_response_text))]
    mock_openai_response.usage.total_tokens = 10

    # No dependency override needed as we removed the signature validation dependency
    # But we MUST provide the 'shop' query parameter as the controller manually extracts it.

    # Patch in the module where the function is used (shopify.proxy)
    with patch("src.main.api.shopify.proxy.validate_shop_and_quota", return_value=mock_auth_context) as mock_validate:
        with patch("src.main.api.shopify.proxy.process_generation_request", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = {
                "status": "success",
                "data": {"title": "My Title", "description": "My Description"}
            }

            response = client.post(
                "/api/proxy/generate-copy?shop=test-shop.myshopify.com",
                json={
                    "product_name": "Proxy Product",
                    "japanese_description": "Proxy Desc",
                    "category": "Proxy Cat"
                }
            )

            assert response.status_code == 200
            json_resp = response.json()
            assert json_resp["status"] == "success"
            assert json_resp["data"]["title"] == "My Title"
            assert json_resp["data"]["description"] == "My Description"
        
        mock_validate.assert_called_once()
        mock_process.assert_called_once()

def test_proxy_generate_copy_missing_shop():
    """Test proxy endpoint fails correctly when shop param is missing."""
    
    response = client.post(
        "/api/proxy/generate-copy", # No shop param
        json={
            "product_name": "Proxy Product",
            "japanese_description": "Proxy Desc"
        }
    )
    assert response.status_code == 400
    assert "Missing shop parameter" in response.json()["detail"]

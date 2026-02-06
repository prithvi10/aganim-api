import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session
from datetime import date
import httpx

from src.main.api.main import app
from src.main.db.database import get_db
from src.main.db.db_models import User, Plan

# Initialize Test Client
client = TestClient(app, raise_server_exceptions=False)

# Mock DB
def mock_get_db():
    db = MagicMock(spec=Session)
    return db

app.dependency_overrides[get_db] = mock_get_db

@pytest.fixture
def mock_auth_context():
    mock_user = MagicMock(spec=User)
    mock_user.username = "test-shop.myshopify.com"
    mock_user.id = 1 
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    
    return {
        "user": mock_user,
        "plan": mock_plan,
    }

@pytest.fixture
def mock_openai_response():
    mock_response_text = '{"title": "My Title", "description": "My Description"}'
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=mock_response_text))]
    mock_resp.usage.total_tokens = 10
    return mock_resp

@pytest.mark.asyncio
async def test_proxy_generate_copy_saves_to_shopify_success(mock_auth_context, mock_openai_response):
    """
    Test that when product_id is provided, the code calls Shopify Admin API to update the product.
    """
    shop_domain = "test-shop.myshopify.com"
    product_id = 987654321
    access_token = "shpat_123456"

    # Mock success response from Shopify
    mock_shopify_response = MagicMock()
    mock_shopify_response.status_code = 200
    mock_shopify_response.text = "{}"

    # Setup mocks - patch in the module where they are used
    with patch("src.main.api.shopify.proxy.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.shopify.proxy.record_successful_rewrite"), \
         patch("src.main.core.generation.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.core.generation.get_shop_access_token", return_value=access_token) as mock_get_token, \
         patch("src.main.core.generation.save_product_content_with_locale") as mock_save:
        
        mock_save.return_value = None

        # Execute
        response = client.post(
            f"/api/proxy/generate-copy?shop={shop_domain}",
            json={
                "product_name": "Test Product",
                "japanese_description": "Test Desc",
                "category": "Test Cat",
                "product_id": product_id
            }
        )

        # Assertions
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        
        # Verify Token Retrieval
        mock_get_token.assert_called_once()
        
        # Verify Shopify API Call
        mock_save.assert_called_once()
        call_args = mock_save.call_args[1]
        
        assert call_args["shop_domain"] == shop_domain
        assert call_args["access_token"] == access_token
        assert call_args["product_id"] == product_id
        assert call_args["title"] == "My Title"
        assert call_args["description"] == "My Description"

@pytest.mark.asyncio
async def test_proxy_generate_copy_shopify_api_failure(mock_auth_context, mock_openai_response):
    """
    Test that if Shopify API fails, the endpoint returns a 500 error.
    """
    shop_domain = "test-shop.myshopify.com"
    product_id = 12345
    access_token = "shpat_fail"

    # Mock failure response from Shopify
    mock_shopify_response = MagicMock()
    mock_shopify_response.status_code = 422
    mock_shopify_response.text = '{"errors": {"title": ["cannot be blank"]}}'

    with patch("src.main.api.shopify.proxy.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.shopify.proxy.record_successful_rewrite"), \
         patch("src.main.core.generation.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.core.generation.get_shop_access_token", return_value=access_token), \
         patch("src.main.core.generation.save_product_content_with_locale", side_effect=Exception("Failed to update product: 422")):
        
        response = client.post(
            f"/api/proxy/generate-copy?shop={shop_domain}",
            json={
                "product_name": "Test Product",
                "japanese_description": "Test Desc",
                "product_id": product_id
            }
        )

        assert response.status_code == 500
        assert "Failed to update product" in response.json()["detail"]

@pytest.mark.asyncio
async def test_proxy_generate_copy_no_product_id_skips_update(mock_auth_context, mock_openai_response):
    """
    Test that if product_id is NOT provided, the code skips the Shopify update but still returns generated text.
    """
    shop_domain = "test-shop.myshopify.com"

    with patch("src.main.api.shopify.proxy.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.shopify.proxy.record_successful_rewrite"), \
         patch("src.main.core.generation.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.core.generation.get_shop_access_token") as mock_get_token, \
         patch("src.main.core.generation.save_product_content_with_locale") as mock_save:
        
        response = client.post(
            f"/api/proxy/generate-copy?shop={shop_domain}",
            json={
                "product_name": "Test Product",
                "japanese_description": "Test Desc"
                # product_id MISSING
            }
        )

        assert response.status_code == 200
        assert response.json()["data"]["title"] == "My Title"
        
        # Verify NO token retrieval or API call
        mock_get_token.assert_not_called()
        mock_save.assert_not_called()

@pytest.mark.asyncio
async def test_proxy_generate_copy_missing_access_token(mock_auth_context, mock_openai_response):
    """
    Test failure when access token is missing in DB.
    """
    shop_domain = "test-shop.myshopify.com"
    product_id = 555

    with patch("src.main.api.shopify.proxy.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.shopify.proxy.record_successful_rewrite"), \
         patch("src.main.core.generation.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.core.generation.get_shop_access_token", return_value=None): # No token
        
        response = client.post(
            f"/api/proxy/generate-copy?shop={shop_domain}",
            json={
                "product_name": "Test Product",
                "japanese_description": "Test Desc",
                "product_id": product_id
            }
        )

        assert response.status_code == 500
        assert "Shopify Access Token not found" in response.json()["detail"]

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session
from datetime import date
import httpx

from src.main.api.main import app
from src.main.db.database import get_db
from src.main.db.db_models import User, Plan

client = TestClient(app)

# --- Mocks ---
def mock_get_db():
    return MagicMock(spec=Session)

app.dependency_overrides[get_db] = mock_get_db

@pytest.fixture
def mock_auth_context():
    mock_user = MagicMock(spec=User)
    mock_user.username = "test-shop.myshopify.com"
    mock_user.id = 1 
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    return {
        "user": mock_user, "plan": mock_plan, "user_id": 1,
        "billing_cycle_start": date(2023, 1, 1), "current_usage": 0
    }

@pytest.fixture
def mock_openai_response():
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"title": "New", "description": "New"}'))]
    mock_resp.usage.total_tokens = 10
    return mock_resp

@pytest.mark.asyncio
async def test_get_shop_locales_success(mock_auth_context):
    """Test fetching shop locales via proxy endpoint."""
    shop = "test-shop.myshopify.com"
    
    # Mock Shopify Response
    mock_shopify_resp = MagicMock()
    mock_shopify_resp.status_code = 200
    mock_shopify_resp.json.return_value = {
        "data": {
            "shopLocales": [
                {"locale": "en", "primary": True},
                {"locale": "fr", "primary": False}
            ]
        }
    }

    with patch("src.main.api.controller.get_shop_access_token", return_value="token"), \
         patch("src.main.api.controller.httpx.AsyncClient") as MockClient:
        
        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post = AsyncMock(return_value=mock_shopify_resp)

        response = client.get(f"/api/proxy/shop/locales?shop={shop}")

        assert response.status_code == 200
        assert len(response.json()["locales"]) == 2
        assert response.json()["locales"][0]["locale"] == "en"

@pytest.mark.asyncio
async def test_controller_updates_primary_locale_via_rest(mock_auth_context, mock_openai_response):
    """Test that Primary Locale updates use REST API."""
    shop = "test-shop.myshopify.com"
    
    # Mock Shop Info (Primary = en)
    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    # Mock Product Update (REST)
    mock_update_resp = MagicMock()
    mock_update_resp.status_code = 200

    with patch("src.main.api.controller.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.controller.update_token_usage"), \
         patch("src.main.api.controller.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.api.controller.get_shop_access_token", return_value="token"), \
         patch("src.main.api.controller.httpx.AsyncClient") as MockClient, \
         patch("src.main.api.controller.limiter.is_allowed", return_value=True): # Mock Rate Limiter

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        
        # 1. Shop Info Call -> 2. REST Update Call
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)
        mock_client.put = AsyncMock(return_value=mock_update_resp)

        response = client.post(
            f"/api/proxy/generate-copy?shop={shop}",
            json={
                "product_name": "P", "japanese_description": "D", 
                "product_id": 123, "target_locale": "en" # Matches Primary
            }
        )

        assert response.status_code == 200
        
        # Verify REST PUT was called
        mock_client.put.assert_called_once()
        assert "products/123.json" in mock_client.put.call_args[0][0]

@pytest.mark.asyncio
async def test_controller_updates_secondary_locale_via_graphql(mock_auth_context, mock_openai_response):
    """Test that Secondary Locale updates call the GraphQL Service."""
    shop = "test-shop.myshopify.com"

    # Mock Shop Info (Primary = en)
    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    with patch("src.main.api.controller.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.controller.update_token_usage"), \
         patch("src.main.api.controller.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.api.controller.get_shop_access_token", return_value="token"), \
         patch("src.main.api.controller.httpx.AsyncClient") as MockClient, \
         patch("src.main.api.controller.create_shopify_translation", new_callable=AsyncMock) as mock_create_translation:

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp) # For Primary Locale check

        response = client.post(
            f"/api/proxy/generate-copy?shop={shop}",
            json={
                "product_name": "P", "japanese_description": "D", 
                "product_id": 123, "target_locale": "fr" # Secondary Locale
            }
        )

        assert response.status_code == 200
        
        # Verify GraphQL Service was called
        mock_create_translation.assert_called_once()
        kwargs = mock_create_translation.call_args[1]
        assert kwargs["target_locale"] == "fr"
        assert kwargs["product_id"] == 123

@pytest.mark.asyncio
async def test_controller_translation_service_failure(mock_auth_context, mock_openai_response):
    """Test controller handling of translation service failure."""
    shop = "test-shop.myshopify.com"
    
    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    with patch("src.main.api.controller.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.controller.update_token_usage"), \
         patch("src.main.api.controller.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.api.controller.get_shop_access_token", return_value="token"), \
         patch("src.main.api.controller.httpx.AsyncClient") as MockClient, \
         patch("src.main.api.controller.create_shopify_translation", side_effect=Exception("GraphQL Service Down")):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        response = client.post(
            f"/api/proxy/generate-copy?shop={shop}",
            json={
                "product_name": "P", "japanese_description": "D", 
                "product_id": 123, "target_locale": "fr"
            }
        )

        assert response.status_code == 500
        assert "GraphQL Service Down" in response.json()["detail"]


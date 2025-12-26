import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from datetime import date

from src.main.api.main import app
from src.main.db.database import get_db
from src.main.db.db_models import User, Plan

client = TestClient(app)

# --- Common Test Fixtures ---
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
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"title": "Translated Title", "description": "Translated Desc"}'))]
    mock_resp.usage.total_tokens = 50
    return mock_resp

@pytest.mark.asyncio
async def test_integration_multilang_happy_path(mock_auth_context, mock_openai_response):
    """
    Case 1: Happy Path.
    Merchant wants to translate to 'fr' (French).
    'fr' IS enabled/published in Shopify settings.
    Result: Backend should successfully call the GraphQL translation service.
    """
    shop = "test-shop.myshopify.com"
    target_locale = "fr"
    
    # 1. Mock Shop Info (Primary = en)
    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    # 2. Mock Translation Service (GraphQL) Success
    # We mock the service function directly to simulate a successful integration call
    with patch("src.main.api.controller.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.controller.update_token_usage"), \
         patch("src.main.api.controller.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.api.controller.get_shop_access_token", return_value="valid_token"), \
         patch("src.main.api.controller.httpx.AsyncClient") as MockClient, \
         patch("src.main.api.controller.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.api.controller.limiter.is_allowed", return_value=True): # Mock Rate Limiter

        # Setup Client Mock for Primary Locale Check
        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        mock_save_content.return_value = True

        # Execute Request
        response = client.post(
            f"/api/proxy/generate-copy?shop={shop}",
            json={
                "product_name": "Test Product",
                "japanese_description": "Test Desc",
                "product_id": 12345,
                "target_locale": target_locale
            }
        )

        # Assertions
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        
        mock_save_content.assert_called_once()
        kwargs = mock_save_content.call_args[1]
        assert kwargs["target_locale"] == "fr"
        assert kwargs["product_id"] == 12345
        assert kwargs["title"] == "Translated Title"

@pytest.mark.asyncio
async def test_integration_multilang_missing_locale(mock_auth_context, mock_openai_response):
    """
    Case 2: Missing Locale.
    Merchant tries to translate to 'de' (German).
    However, the backend logic *technically* doesn't block this based on fetching locales first 
    (it assumes the frontend dropdown is the source of truth).
    
    BUT, if we want to simulate what happens if they send a locale that Shopify REJECTS 
    (e.g., creating a translation for a locale not enabled on the shop),
    we mock the `create_shopify_translation` service throwing an error.
    
    This effectively tests the integration handling of a Shopify API rejection.
    """
    shop = "test-shop.myshopify.com"
    target_locale = "de" # German (Assume not enabled on shop)
    
    # 1. Mock Shop Info (Primary = en)
    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    # 2. Mock Translation Service Failure
    # Simulating Shopify GraphQL error: "Locale not enabled"
    error_message = "Shopify Translation Error: Locale 'de' is not enabled for this shop."
    
    with patch("src.main.api.controller.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.controller.update_token_usage"), \
         patch("src.main.api.controller.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.api.controller.get_shop_access_token", return_value="valid_token"), \
         patch("src.main.api.controller.httpx.AsyncClient") as MockClient, \
         patch("src.main.api.controller.save_product_content_with_locale", side_effect=Exception(error_message)), \
         patch("src.main.api.controller.limiter.is_allowed", return_value=True): # Mock Rate Limiter

        # Setup Client Mock for Primary Locale Check
        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        # Execute Request
        response = client.post(
            f"/api/proxy/generate-copy?shop={shop}",
            json={
                "product_name": "Test Product",
                "japanese_description": "Test Desc",
                "product_id": 12345,
                "target_locale": target_locale
            }
        )

        # Assertions
        assert response.status_code == 500
        # The detailed error from the service should be propagated
        assert "Locale 'de' is not enabled" in response.json()["detail"]


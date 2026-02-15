import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from datetime import date

from src.ecommerce.api.main import app
from src.shared.db.database import get_db
from src.ecommerce.db.models import User, Plan

client = TestClient(app, raise_server_exceptions=False)

# --- Common Test Fixtures ---
def mock_get_db():
    return MagicMock(spec=Session)

@pytest.fixture(autouse=True)
def _ensure_db_override():
    """
    CI note: other test modules may delete/replace app.dependency_overrides[get_db] in teardown.
    Ensure our override is active for the duration of each test in this module.
    """
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = mock_get_db
    try:
        yield
    finally:
        if prev is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = prev

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
    # Patch in the proxy module where validate_shop_and_quota is used
    with patch("src.ecommerce.api.shopify.proxy.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.ecommerce.api.shopify.proxy.record_successful_rewrite"), \
         patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="valid_token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True): # Mock Rate Limiter

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
    
    # Patch in the proxy module where validate_shop_and_quota is used
    with patch("src.ecommerce.api.shopify.proxy.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.ecommerce.api.shopify.proxy.record_successful_rewrite"), \
         patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="valid_token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", side_effect=Exception(error_message)), \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True): # Mock Rate Limiter

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


@pytest.mark.asyncio
async def test_integration_optimize_bulk_with_serp_context(mock_auth_context, mock_openai_response):
    shop = "test-shop.myshopify.com"
    mock_auth_context["plan"].name = "Standard"

    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    serp_results = [{"title": "A", "snippet": "S1", "url": "https://a.example"}]

    # Use FastAPI's dependency override for resolve_shop_domain
    from src.ecommerce.api.shopify.shared import resolve_shop_domain
    async def mock_resolve_shop():
        return shop
    
    app.dependency_overrides[resolve_shop_domain] = mock_resolve_shop
    try:
        # Patch other dependencies
        with patch("src.ecommerce.api.shopify.proxy.validate_shop_and_quota", return_value=mock_auth_context), \
             patch("src.ecommerce.api.shopify.proxy.record_successful_rewrite"), \
             patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=mock_openai_response) as mock_generate, \
             patch("src.ecommerce.core.generation.get_shop_access_token", return_value="valid_token"), \
             patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
             patch("src.ecommerce.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=serp_results), \
             patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock), \
             patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True):

            mock_client = MockClient.return_value
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

            response = client.post(
                "/api/proxy/generate-bulk",
                json={
                    "product_name": "Test Product",
                    "japanese_description": "Test Desc",
                    "product_id": 12345,
                    "target_locales": ["en"],
                    "category": "Tea",
                },
            )

            assert response.status_code == 200
            assert response.json()["status"] == "success"
            _, kwargs = mock_generate.call_args
            assert kwargs.get("competitor_context") == serp_results
    finally:
        app.dependency_overrides.pop(resolve_shop_domain, None)

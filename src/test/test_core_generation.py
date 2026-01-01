import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session
from datetime import date
import httpx
from src.main.core.generation import process_generation_request
from src.main.db.db_models import User, Plan
from src.main.api.models import RewriteRequest

@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)

@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.username = "test-shop.myshopify.com"
    return user

@pytest.fixture
def mock_plan():
    plan = MagicMock(spec=Plan)
    plan.can_stream_responses = False
    return plan

@pytest.fixture
def mock_openai_response():
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"title": "New", "description": "New"}'))]
    mock_resp.usage.total_tokens = 10
    return mock_resp

@pytest.mark.asyncio
async def test_process_generation_updates_primary_locale_via_rest(mock_db, mock_user, mock_plan, mock_openai_response):
    """Test that Primary Locale updates use REST API in core logic."""
    request = RewriteRequest(
        product_name="P", japanese_description="D", 
        product_id=123, target_locale="en"
    )
    
    # Mock Shop Info (Primary = en)
    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    # Mock Product Update (GraphQL)
    mock_update_resp = MagicMock()
    mock_update_resp.status_code = 200
    mock_update_resp.json.return_value = {
        "data": {
            "productUpdate": {
                "userErrors": []
            }
        }
    }

    with patch("src.main.core.generation.update_token_usage"), \
         patch("src.main.core.generation.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.main.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.main.core.generation.limiter.is_allowed", return_value=True):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)
        mock_client.post = AsyncMock(return_value=mock_update_resp)

        result = await process_generation_request(
            db=mock_db,
            request=request,
            user=mock_user,
            plan=mock_plan,
            user_id=1,
            billing_cycle_start=date(2023, 1, 1)
        )

        assert result["status"] == "success"
        mock_client.post.assert_called_once()
        assert "graphql.json" in mock_client.post.call_args[0][0]

@pytest.mark.asyncio
async def test_process_generation_updates_secondary_locale_via_graphql(mock_db, mock_user, mock_plan, mock_openai_response):
    """Test that Secondary Locale updates call the GraphQL Service in core logic."""
    request = RewriteRequest(
        product_name="P", japanese_description="D", 
        product_id=123, target_locale="fr"
    )
    
    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    with patch("src.main.core.generation.update_token_usage"), \
         patch("src.main.core.generation.openai_service.generate_copy", return_value=mock_openai_response), \
         patch("src.main.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.main.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.main.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.core.generation.limiter.is_allowed", return_value=True):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        result = await process_generation_request(
            db=mock_db,
            request=request,
            user=mock_user,
            plan=mock_plan,
            user_id=1,
            billing_cycle_start=date(2023, 1, 1)
        )

        assert result["status"] == "success"
        mock_save_content.assert_called_once()
        kwargs = mock_save_content.call_args[1]
        assert kwargs["target_locale"] == "fr"


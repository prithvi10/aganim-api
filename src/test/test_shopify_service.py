import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.main.services.shopify_service import create_shopify_translation

@pytest.fixture
def mock_httpx_client():
    with patch("src.main.services.shopify_service.httpx.AsyncClient") as mock_client:
        mock_instance = mock_client.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        # Must configure post to be async (AsyncMock)
        mock_instance.post = AsyncMock() 
        yield mock_instance

@pytest.mark.asyncio
async def test_create_shopify_translation_success(mock_httpx_client):
    """Test successful translation registration."""
    shop_domain = "test-shop.myshopify.com"
    access_token = "test_token"
    product_id = 123
    title = "Translated Title"
    desc = "Translated Desc"
    target_locale = "zh-TW"

    # Mock Digest Response (Step 1)
    mock_digest_response = MagicMock()
    mock_digest_response.status_code = 200
    mock_digest_response.json.return_value = {
        "data": {
            "translatableResource": {
                "translatableContent": [
                    {"key": "title", "digest": "digest_title", "value": "Old Title"},
                    {"key": "body_html", "digest": "digest_desc", "value": "Old Desc"}
                ]
            }
        }
    }

    # Mock Mutation Response (Step 2)
    mock_mutation_response = MagicMock()
    mock_mutation_response.status_code = 200
    mock_mutation_response.json.return_value = {
        "data": {
            "translationsRegister": {
                "userErrors": [],
                "translations": [
                    {"locale": "zh-TW", "key": "title", "value": "Translated Title"}
                ]
            }
        }
    }

    # Sequence of responses
    mock_httpx_client.post.side_effect = [mock_digest_response, mock_mutation_response]

    # Execute
    result = await create_shopify_translation(
        shop_domain, access_token, product_id, title, desc, target_locale
    )

    assert result is None
    assert mock_httpx_client.post.call_count == 2
    
    # Verify Digest Query
    call_args_1 = mock_httpx_client.post.call_args_list[0]
    assert "translatableResource" in call_args_1[1]["json"]["query"]
    
    # Verify Mutation Query includes digests
    call_args_2 = mock_httpx_client.post.call_args_list[1]
    mutation_vars = call_args_2[1]["json"]["variables"]
    assert mutation_vars["translations"][0]["translatableContentDigest"] == "digest_title"
    assert mutation_vars["translations"][1]["translatableContentDigest"] == "digest_desc"

@pytest.mark.asyncio
async def test_create_shopify_translation_digest_fetch_fail(mock_httpx_client):
    """Test failure during digest fetching."""
    mock_digest_response = MagicMock()
    mock_digest_response.status_code = 401 # Unauthorized
    mock_digest_response.text = "Unauthorized"
    
    mock_httpx_client.post.return_value = mock_digest_response

    with pytest.raises(Exception) as excinfo:
        await create_shopify_translation(
            "shop", "token", 123, "title", "desc", "fr"
        )
    
    assert "Failed to fetch content digests: 401" in str(excinfo.value)

@pytest.mark.asyncio
async def test_create_shopify_translation_graphql_error_in_digest(mock_httpx_client):
    """Test GraphQL error payload during digest fetch."""
    mock_digest_response = MagicMock()
    mock_digest_response.status_code = 200
    mock_digest_response.json.return_value = {
        "errors": [{"message": "Syntax Error"}]
    }
    
    mock_httpx_client.post.return_value = mock_digest_response

    with pytest.raises(Exception) as excinfo:
        await create_shopify_translation(
            "shop", "token", 123, "title", "desc", "fr"
        )
    
    assert "Failed to fetch content digests due to GraphQL error" in str(excinfo.value)

@pytest.mark.asyncio
async def test_create_shopify_translation_mutation_fail(mock_httpx_client):
    """Test failure during mutation execution."""
    # Digest success
    mock_digest_response = MagicMock()
    mock_digest_response.status_code = 200
    mock_digest_response.json.return_value = {
        "data": {
            "translatableResource": {
                "translatableContent": [
                    {"key": "title", "digest": "digest_title"},
                    {"key": "body_html", "digest": "digest_desc"}
                ]
            }
        }
    }
    
    # Mutation failure (HTTP)
    mock_mutation_response = MagicMock()
    mock_mutation_response.status_code = 500
    mock_mutation_response.text = "Server Error"

    mock_httpx_client.post.side_effect = [mock_digest_response, mock_mutation_response]

    with pytest.raises(Exception) as excinfo:
        await create_shopify_translation(
            "shop", "token", 123, "title", "desc", "fr"
        )
    
    assert "Failed to register translation" in str(excinfo.value)

@pytest.mark.asyncio
async def test_create_shopify_translation_user_errors(mock_httpx_client):
    """Test Shopify userErrors (logic errors) in mutation."""
    # Digest success
    mock_digest_response = MagicMock()
    mock_digest_response.status_code = 200
    mock_digest_response.json.return_value = {
        "data": {
            "translatableResource": {
                "translatableContent": [
                    {"key": "title", "digest": "digest_title"},
                    {"key": "body_html", "digest": "digest_desc"}
                ]
            }
        }
    }
    
    # Mutation with User Errors
    mock_mutation_response = MagicMock()
    mock_mutation_response.status_code = 200
    mock_mutation_response.json.return_value = {
        "data": {
            "translationsRegister": {
                "userErrors": [{"message": "Digest mismatch", "field": ["digest"]}]
            }
        }
    }

    mock_httpx_client.post.side_effect = [mock_digest_response, mock_mutation_response]

    with pytest.raises(Exception) as excinfo:
        await create_shopify_translation(
            "shop", "token", 123, "title", "desc", "fr"
        )
    
    assert "Shopify Translation Error: Digest mismatch" in str(excinfo.value)


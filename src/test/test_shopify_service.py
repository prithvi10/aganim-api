import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.main.services.shopify_service import (
    create_shopify_translation,
    save_product_content_with_locale,
    save_product_metafields,
)

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


# =============================================================================
# Tests: save_product_content_with_locale
# =============================================================================

@pytest.mark.asyncio
async def test_save_product_content_with_locale_primary_locale(mock_httpx_client):
    """Test saving to primary locale uses productUpdate mutation."""
    shop_domain = "test-shop.myshopify.com"
    access_token = "test_token"
    product_id = 12345
    title = "Updated Title"
    description = "<p>Updated description</p>"
    target_locale = "en"
    primary_locale = "en"  # Same as target
    
    # Mock successful productUpdate response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": {"id": f"gid://shopify/Product/{product_id}", "title": title, "descriptionHtml": description},
                "userErrors": []
            }
        }
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    await save_product_content_with_locale(
        shop_domain, access_token, product_id, title, description, target_locale, primary_locale
    )
    
    # Verify productUpdate was called
    assert mock_httpx_client.post.called
    call_args = mock_httpx_client.post.call_args
    assert "productUpdate" in call_args[1]["json"]["query"]
    
    # Verify correct product data
    variables = call_args[1]["json"]["variables"]
    assert variables["input"]["title"] == title
    assert variables["input"]["descriptionHtml"] == description


@pytest.mark.asyncio
async def test_save_product_content_with_locale_secondary_locale(mock_httpx_client):
    """Test saving to secondary locale uses translation API."""
    shop_domain = "test-shop.myshopify.com"
    access_token = "test_token"
    product_id = 12345
    title = "翻訳されたタイトル"
    description = "<p>翻訳された説明</p>"
    target_locale = "ja"
    primary_locale = "en"  # Different from target
    
    # Mock digest fetch response
    mock_digest_response = MagicMock()
    mock_digest_response.status_code = 200
    mock_digest_response.json.return_value = {
        "data": {
            "translatableResource": {
                "translatableContent": [
                    {"key": "title", "digest": "title_digest"},
                    {"key": "body_html", "digest": "body_digest"}
                ]
            }
        }
    }
    
    # Mock translation register response
    mock_translation_response = MagicMock()
    mock_translation_response.status_code = 200
    mock_translation_response.json.return_value = {
        "data": {
            "translationsRegister": {
                "userErrors": []
            }
        }
    }
    
    mock_httpx_client.post.side_effect = [mock_digest_response, mock_translation_response]
    
    await save_product_content_with_locale(
        shop_domain, access_token, product_id, title, description, target_locale, primary_locale
    )
    
    # Verify 2 calls: digest fetch + translation register
    assert mock_httpx_client.post.call_count == 2
    
    # Verify second call is translationsRegister
    second_call = mock_httpx_client.post.call_args_list[1]
    assert "translationsRegister" in second_call[1]["json"]["query"]


@pytest.mark.asyncio
async def test_save_product_content_with_locale_graphql_error(mock_httpx_client):
    """Test handling of GraphQL errors."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "errors": [{"message": "Invalid product ID"}]
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    with pytest.raises(Exception) as excinfo:
        await save_product_content_with_locale(
            "shop.myshopify.com", "token", 123, "title", "desc", "en", "en"
        )
    
    assert "GraphQL Syntax Error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_save_product_content_with_locale_user_errors(mock_httpx_client):
    """Test handling of productUpdate userErrors."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": None,
                "userErrors": [{"field": ["title"], "message": "Title is too long"}]
            }
        }
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    with pytest.raises(Exception) as excinfo:
        await save_product_content_with_locale(
            "shop.myshopify.com", "token", 123, "title", "desc", "en", "en"
        )
    
    assert "Title is too long" in str(excinfo.value)


@pytest.mark.asyncio
async def test_save_product_content_with_locale_http_error(mock_httpx_client):
    """Test handling of HTTP errors."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    
    mock_httpx_client.post.return_value = mock_response
    
    with pytest.raises(Exception) as excinfo:
        await save_product_content_with_locale(
            "shop.myshopify.com", "token", 123, "title", "desc", "en", "en"
        )
    
    assert "Failed to update product" in str(excinfo.value)


# =============================================================================
# Tests: save_product_metafields
# =============================================================================

@pytest.mark.asyncio
async def test_save_product_metafields_success(mock_httpx_client):
    """Test successful metafield save."""
    shop_domain = "test-shop.myshopify.com"
    access_token = "test_token"
    product_id = 12345
    metafields = [
        {
            "namespace": "crossborder_agent",
            "key": "social_hooks",
            "value": '[{"type": "Story", "caption": "Test"}]',
            "type": "json"
        },
        {
            "namespace": "crossborder_agent",
            "key": "pricing_analysis",
            "value": '{"recommended_price": 29.99}',
            "type": "json"
        }
    ]
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": {
                    "id": f"gid://shopify/Product/{product_id}",
                    "metafields": {"edges": []}
                },
                "userErrors": []
            }
        }
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    await save_product_metafields(shop_domain, access_token, product_id, metafields)
    
    # Verify API was called
    assert mock_httpx_client.post.called
    call_args = mock_httpx_client.post.call_args
    
    # Verify mutation
    assert "productUpdate" in call_args[1]["json"]["query"]
    
    # Verify metafields in variables
    variables = call_args[1]["json"]["variables"]
    assert len(variables["input"]["metafields"]) == 2
    assert variables["input"]["metafields"][0]["namespace"] == "crossborder_agent"
    assert variables["input"]["metafields"][0]["key"] == "social_hooks"


@pytest.mark.asyncio
async def test_save_product_metafields_with_gid_format(mock_httpx_client):
    """Test metafield save with GID format product ID."""
    product_gid = "gid://shopify/Product/12345"
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": {"id": product_gid, "metafields": {"edges": []}},
                "userErrors": []
            }
        }
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    await save_product_metafields(
        "shop.myshopify.com",
        "token",
        product_gid,  # Pass GID directly
        [{"namespace": "test", "key": "test", "value": "test", "type": "single_line_text_field"}]
    )
    
    # Verify GID was used as-is, not wrapped
    call_args = mock_httpx_client.post.call_args
    variables = call_args[1]["json"]["variables"]
    assert variables["input"]["id"] == product_gid


@pytest.mark.asyncio
async def test_save_product_metafields_http_error(mock_httpx_client):
    """Test handling of HTTP errors."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    
    mock_httpx_client.post.return_value = mock_response
    
    with pytest.raises(Exception) as excinfo:
        await save_product_metafields(
            "shop.myshopify.com",
            "token",
            123,
            [{"namespace": "test", "key": "test", "value": "test", "type": "json"}]
        )
    
    assert "Failed to save metafields" in str(excinfo.value)


@pytest.mark.asyncio
async def test_save_product_metafields_graphql_error(mock_httpx_client):
    """Test handling of GraphQL syntax errors."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "errors": [{"message": "Parse error on line 1"}]
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    with pytest.raises(Exception) as excinfo:
        await save_product_metafields(
            "shop.myshopify.com",
            "token",
            123,
            [{"namespace": "test", "key": "test", "value": "test", "type": "json"}]
        )
    
    assert "GraphQL Syntax Error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_save_product_metafields_user_errors(mock_httpx_client):
    """Test handling of metafield user errors."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": None,
                "userErrors": [{"field": ["metafields"], "message": "Invalid metafield type"}]
            }
        }
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    with pytest.raises(Exception) as excinfo:
        await save_product_metafields(
            "shop.myshopify.com",
            "token",
            123,
            [{"namespace": "test", "key": "test", "value": "test", "type": "invalid_type"}]
        )
    
    assert "Invalid metafield type" in str(excinfo.value)


@pytest.mark.asyncio
async def test_save_product_metafields_empty_list(mock_httpx_client):
    """Test saving empty metafields list."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": {"id": "gid://shopify/Product/123", "metafields": {"edges": []}},
                "userErrors": []
            }
        }
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    # Should not raise, just send empty metafields array
    await save_product_metafields(
        "shop.myshopify.com",
        "token",
        123,
        []
    )
    
    call_args = mock_httpx_client.post.call_args
    variables = call_args[1]["json"]["variables"]
    assert variables["input"]["metafields"] == []


@pytest.mark.asyncio
async def test_save_product_metafields_default_type(mock_httpx_client):
    """Test that metafield type defaults to 'json'."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": {"id": "gid://shopify/Product/123", "metafields": {"edges": []}},
                "userErrors": []
            }
        }
    }
    
    mock_httpx_client.post.return_value = mock_response
    
    # Metafield without explicit type
    await save_product_metafields(
        "shop.myshopify.com",
        "token",
        123,
        [{"namespace": "test", "key": "test", "value": '{"data": true}'}]  # No type specified
    )
    
    call_args = mock_httpx_client.post.call_args
    variables = call_args[1]["json"]["variables"]
    # Should default to "json"
    assert variables["input"]["metafields"][0]["type"] == "json"


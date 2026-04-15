"""
Unit tests for new Shopify service helpers added for autonomous publishing.

Tests:
- get_shop_credentials
- update_product_body
- update_variant_price
- create_article
- trigger_flow_event
- update_product_seo
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.services.shopify_service import (
    get_shop_credentials,
    update_product_body,
    update_variant_price,
    create_article,
    trigger_flow_event,
    update_product_seo,
)


# =============================================================================
# Tests: get_shop_credentials
# =============================================================================

class TestGetShopCredentials:
    """Tests for the get_shop_credentials helper."""

    def test_returns_credentials_for_known_shop(self):
        """Test that valid shop returns all credential fields."""
        mock_shop = MagicMock()
        mock_shop.access_token = "shpat_abc123"
        mock_shop.price_guardrails = {"min_price": 10, "max_price": 200}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_shop

        result = get_shop_credentials(mock_db, "test-shop.myshopify.com")

        assert result["access_token"] == "shpat_abc123"
        assert result["price_guardrails"]["min_price"] == 10

    def test_returns_empty_dict_for_unknown_shop(self):
        """Test that unknown shop returns empty dict."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = get_shop_credentials(mock_db, "unknown-shop.myshopify.com")

        assert result == {}

    def test_handles_missing_optional_fields(self):
        """Test graceful handling when optional fields are missing from model."""
        mock_shop = MagicMock(spec=[])  # Empty spec — getattr will be used
        mock_shop.access_token = "shpat_abc"
        mock_shop.domain = "shop.myshopify.com"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_shop

        result = get_shop_credentials(mock_db, "shop.myshopify.com")

        assert result["access_token"] == "shpat_abc"


# =============================================================================
# Tests: update_product_body
# =============================================================================

@pytest.mark.asyncio
async def test_update_product_body_success():
    """Test successful product body update via GraphQL."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": {"id": "gid://shopify/Product/123", "descriptionHtml": "<p>New</p>"},
                "userErrors": [],
            }
        }
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        # Should not raise
        await update_product_body(
            shop_domain="test.myshopify.com",
            access_token="shpat_test",
            product_id=123,
            html="<p>New description</p>",
        )

    # Verify GraphQL mutation was sent
    call_args = mock_client.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json", {})
    assert "productUpdate" in payload["query"]
    assert payload["variables"]["input"]["descriptionHtml"] == "<p>New description</p>"


@pytest.mark.asyncio
async def test_update_product_body_handles_gid_format():
    """Test that product_id in GID format is preserved."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {"productUpdate": {"product": {"id": "gid://shopify/Product/123"}, "userErrors": []}}
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        await update_product_body(
            shop_domain="test.myshopify.com",
            access_token="shpat_test",
            product_id="gid://shopify/Product/999",
            html="<p>Test</p>",
        )

    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json", {})
    # GID should be preserved, not double-wrapped
    assert payload["variables"]["input"]["id"] == "gid://shopify/Product/999"


@pytest.mark.asyncio
async def test_update_product_body_raises_on_user_errors():
    """Test that user errors from Shopify raise an exception."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productUpdate": {
                "product": None,
                "userErrors": [{"field": "descriptionHtml", "message": "HTML is invalid"}],
            }
        }
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        with pytest.raises(Exception, match="user error"):
            await update_product_body(
                shop_domain="test.myshopify.com",
                access_token="shpat_test",
                product_id=123,
                html="<bad>",
            )


@pytest.mark.asyncio
async def test_update_product_body_raises_on_http_error():
    """Test that non-200 status raises an exception."""
    mock_response = MagicMock()
    mock_response.status_code = 401

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        with pytest.raises(Exception, match="failed: 401"):
            await update_product_body(
                shop_domain="test.myshopify.com",
                access_token="bad_token",
                product_id=123,
                html="test",
            )


# =============================================================================
# Tests: update_variant_price
# =============================================================================

@pytest.mark.asyncio
async def test_update_variant_price_success():
    """Test successful variant price update."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productVariantUpdate": {
                "productVariant": {"id": "gid://shopify/ProductVariant/456", "price": "29.99"},
                "userErrors": [],
            }
        }
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        await update_variant_price(
            shop_domain="test.myshopify.com",
            access_token="shpat_test",
            variant_id=456,
            price="29.99",
        )

    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json", {})
    assert payload["variables"]["input"]["price"] == "29.99"


@pytest.mark.asyncio
async def test_update_variant_price_raises_on_user_errors():
    """Test that user errors raise an exception."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "productVariantUpdate": {
                "productVariant": None,
                "userErrors": [{"field": "price", "message": "Price must be positive"}],
            }
        }
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        with pytest.raises(Exception, match="user error"):
            await update_variant_price(
                shop_domain="test.myshopify.com",
                access_token="shpat_test",
                variant_id=456,
                price="-1.00",
            )


# =============================================================================
# Tests: create_article
# =============================================================================

@pytest.mark.asyncio
async def test_create_article_success():
    """Test successful blog article creation."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "article": {"id": 789, "title": "My Blog Post", "published_at": "2026-01-01T00:00:00Z"}
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await create_article(
            shop_domain="test.myshopify.com",
            access_token="shpat_test",
            blog_id=101,
            title="My Blog Post",
            body_html="<p>Blog content</p>",
        )

    assert result["id"] == 789
    assert result["title"] == "My Blog Post"


@pytest.mark.asyncio
async def test_create_article_raises_on_error():
    """Test that article creation failure raises an exception."""
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.text = "Unprocessable Entity"

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        with pytest.raises(Exception, match="create_article failed"):
            await create_article(
                shop_domain="test.myshopify.com",
                access_token="shpat_test",
                blog_id=101,
                title="Test",
                body_html="<p>Test</p>",
            )


# =============================================================================
# Tests: trigger_flow_event
# =============================================================================

@pytest.mark.asyncio
async def test_trigger_flow_event_success():
    """Test successful Shopify Flow event trigger."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {"flowTriggerReceive": {"userErrors": []}}
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        await trigger_flow_event(
            shop_domain="test.myshopify.com",
            access_token="shpat_test",
            event_topic="crossborder/marketing-email-launch",
            payload={"product_id": "123", "content": "Email body"},
        )

    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json", {})
    assert "flowTriggerReceive" in payload["query"]


@pytest.mark.asyncio
async def test_trigger_flow_event_raises_on_user_errors():
    """Test that Flow event user errors raise an exception."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {"flowTriggerReceive": {"userErrors": [{"field": "body", "message": "Invalid topic"}]}}
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        with pytest.raises(Exception, match="trigger_flow_event error"):
            await trigger_flow_event(
                shop_domain="test.myshopify.com",
                access_token="shpat_test",
                event_topic="bad/topic",
                payload={},
            )


# =============================================================================
# Tests: update_product_seo
# =============================================================================

@pytest.mark.asyncio
async def test_update_product_seo_success():
    """Test successful product SEO update."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {"productUpdate": {"product": {"id": "gid://shopify/Product/123"}, "userErrors": []}}
    }

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        await update_product_seo(
            shop_domain="test.myshopify.com",
            access_token="shpat_test",
            product_id=123,
            seo_title="Best Ceramic Bowl",
            seo_description="Handcrafted in Kyoto with traditional techniques.",
        )

    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json", {})
    seo_input = payload["variables"]["input"]["seo"]
    assert seo_input["title"] == "Best Ceramic Bowl"
    assert seo_input["description"] == "Handcrafted in Kyoto with traditional techniques."

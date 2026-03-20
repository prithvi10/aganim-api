"""Unit tests for create_product_in_shopify() in shopify_service.py."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.ecommerce.services.shopify_service import create_product_in_shopify


def _mock_graphql_response(product_gid: str = "gid://shopify/Product/999", user_errors=None):
    """Build a mock httpx response for productCreate."""
    data = {
        "data": {
            "productCreate": {
                "product": {"id": product_gid, "title": "Test Product"},
                "userErrors": user_errors or [],
            }
        }
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    return resp


@pytest.mark.asyncio
async def test_happy_path():
    mock_resp = _mock_graphql_response("gid://shopify/Product/12345")

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.post.return_value = mock_resp
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        gid = await create_product_in_shopify(
            shop_domain="test.myshopify.com",
            access_token="token123",
            product_data={
                "title": "Test Product",
                "description_html": "<p>Description</p>",
                "product_type": "General",
            },
        )

    assert gid == "gid://shopify/Product/12345"
    call_args = client_instance.post.call_args
    body = call_args.kwargs.get("json") or call_args[1].get("json")
    variables = body["variables"]["input"]
    assert variables["status"] == "DRAFT"
    assert variables["title"] == "Test Product"


@pytest.mark.asyncio
async def test_with_seo_fields():
    mock_resp = _mock_graphql_response()

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.post.return_value = mock_resp
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        await create_product_in_shopify(
            shop_domain="test.myshopify.com",
            access_token="token123",
            product_data={
                "title": "SEO Product",
                "description_html": "<p>Desc</p>",
                "product_type": "Kitchen",
                "seo_title": "Best Kitchen Product",
                "seo_description": "Top-rated kitchen product for 2026",
            },
        )

    call_args = client_instance.post.call_args
    body = call_args.kwargs.get("json") or call_args[1].get("json")
    variables = body["variables"]["input"]
    assert "seo" in variables
    assert variables["seo"]["title"] == "Best Kitchen Product"
    assert variables["seo"]["description"] == "Top-rated kitchen product for 2026"


@pytest.mark.asyncio
async def test_shopify_user_errors():
    error_resp = _mock_graphql_response(
        user_errors=[{"field": ["title"], "message": "Title is too long"}]
    )

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.post.return_value = error_resp
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(Exception, match="Title is too long"):
            await create_product_in_shopify(
                shop_domain="test.myshopify.com",
                access_token="token123",
                product_data={
                    "title": "X" * 500,
                    "description_html": "",
                    "product_type": "General",
                },
            )


@pytest.mark.asyncio
async def test_draft_status_always_set():
    mock_resp = _mock_graphql_response()

    with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.post.return_value = mock_resp
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        await create_product_in_shopify(
            shop_domain="test.myshopify.com",
            access_token="token123",
            product_data={
                "title": "Draft Product",
                "description_html": "",
                "product_type": "",
            },
        )

    call_args = client_instance.post.call_args
    body = call_args.kwargs.get("json") or call_args[1].get("json")
    variables = body["variables"]["input"]
    assert variables["status"] == "DRAFT"

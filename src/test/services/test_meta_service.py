"""
Unit tests for MetaService - Meta Graph API client.

Tests post_ad for photo posts, text/link posts, error handling,
and edge cases.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from src.main.services.meta_service import MetaService, META_GRAPH_API


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def meta_service():
    """Create a MetaService instance for testing."""
    return MetaService()


@pytest.fixture
def valid_creds():
    """Standard valid credentials for Meta API."""
    return {
        "page_id": "123456789",
        "access_token": "EAAxxxxxxxx",
    }


# =============================================================================
# Tests: post_ad - Photo Posts
# =============================================================================

@pytest.mark.asyncio
async def test_post_ad_photo_success(meta_service, valid_creds):
    """Test successful photo post to Meta page."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "post_12345"}

    with patch("src.main.services.meta_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        success, result = await meta_service.post_ad(
            page_id=valid_creds["page_id"],
            access_token=valid_creds["access_token"],
            caption="Check out our new product! 🎉",
            image_url="https://cdn.shopify.com/product.jpg",
        )

    assert success is True
    assert result == "post_12345"

    # Verify the correct URL was called (photos endpoint for image posts)
    call_args = mock_client.post.call_args
    assert f"/{valid_creds['page_id']}/photos" in call_args[0][0]


@pytest.mark.asyncio
async def test_post_ad_photo_includes_correct_payload(meta_service, valid_creds):
    """Test that photo post sends correct payload."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "post_123"}

    with patch("src.main.services.meta_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await meta_service.post_ad(
            page_id=valid_creds["page_id"],
            access_token=valid_creds["access_token"],
            caption="Test caption",
            image_url="https://example.com/img.jpg",
        )

    call_kwargs = mock_client.post.call_args
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", {})
    assert payload["caption"] == "Test caption"
    assert payload["url"] == "https://example.com/img.jpg"
    assert payload["access_token"] == valid_creds["access_token"]


# =============================================================================
# Tests: post_ad - Text/Link Posts
# =============================================================================

@pytest.mark.asyncio
async def test_post_ad_text_only_success(meta_service, valid_creds):
    """Test successful text-only post (no image)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "post_text_456"}

    with patch("src.main.services.meta_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        success, result = await meta_service.post_ad(
            page_id=valid_creds["page_id"],
            access_token=valid_creds["access_token"],
            caption="Text only post",
        )

    assert success is True
    assert result == "post_text_456"

    # Should use /feed endpoint for text posts
    call_args = mock_client.post.call_args
    assert f"/{valid_creds['page_id']}/feed" in call_args[0][0]


@pytest.mark.asyncio
async def test_post_ad_text_with_link(meta_service, valid_creds):
    """Test text post with link included."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "post_link_789"}

    with patch("src.main.services.meta_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        success, result = await meta_service.post_ad(
            page_id=valid_creds["page_id"],
            access_token=valid_creds["access_token"],
            caption="Check this out!",
            link="https://my-shop.myshopify.com/products/abc",
        )

    assert success is True
    call_kwargs = mock_client.post.call_args
    payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", {})
    assert payload["link"] == "https://my-shop.myshopify.com/products/abc"
    assert payload["message"] == "Check this out!"


# =============================================================================
# Tests: post_ad - Error Handling
# =============================================================================

@pytest.mark.asyncio
async def test_post_ad_api_error_returns_false(meta_service, valid_creds):
    """Test that API error returns (False, error_message)."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    mock_response.json.return_value = {
        "error": {"message": "Invalid OAuth 2.0 Access Token"}
    }

    with patch("src.main.services.meta_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        success, result = await meta_service.post_ad(
            page_id=valid_creds["page_id"],
            access_token="invalid_token",
            caption="Test",
        )

    assert success is False
    assert "Invalid OAuth" in result


@pytest.mark.asyncio
async def test_post_ad_network_exception(meta_service, valid_creds):
    """Test that network exceptions are handled gracefully."""
    with patch("src.main.services.meta_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        success, result = await meta_service.post_ad(
            page_id=valid_creds["page_id"],
            access_token=valid_creds["access_token"],
            caption="Test",
        )

    assert success is False
    assert "Connection refused" in result


@pytest.mark.asyncio
async def test_post_ad_server_error(meta_service, valid_creds):
    """Test handling of 500 server error from Meta API."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.json.return_value = {
        "error": {"message": "An unexpected error has occurred."}
    }

    with patch("src.main.services.meta_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        success, result = await meta_service.post_ad(
            page_id=valid_creds["page_id"],
            access_token=valid_creds["access_token"],
            caption="Test",
        )

    assert success is False
    assert "unexpected error" in result.lower()


@pytest.mark.asyncio
async def test_post_ad_201_status_is_success(meta_service, valid_creds):
    """Test that 201 status code is treated as success."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"post_id": "new_post_99"}

    with patch("src.main.services.meta_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        success, result = await meta_service.post_ad(
            page_id=valid_creds["page_id"],
            access_token=valid_creds["access_token"],
            caption="Test",
            image_url="https://example.com/img.jpg",
        )

    assert success is True
    assert result == "new_post_99"


# =============================================================================
# Tests: META_GRAPH_API constant
# =============================================================================

def test_meta_graph_api_url():
    """Test that META_GRAPH_API points to the Facebook Graph API."""
    assert "graph.facebook.com" in META_GRAPH_API
    assert META_GRAPH_API.startswith("https://")

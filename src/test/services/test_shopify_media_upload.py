"""
Unit tests for Shopify Media Library upload functions:
  - staged_upload_create
  - _upload_to_staged_target
  - file_create
  - upload_media_to_shopify (orchestrator)

Covers:
  - Happy path for each function
  - GraphQL user errors
  - HTTP errors (non-200 status codes)
  - Empty results
  - Full orchestration flow
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.services.shopify_service import (
    staged_upload_create,
    file_create,
    upload_media_to_shopify,
    _upload_to_staged_target,
)


FAKE_IMAGE = b"\x89PNG\r\n\x1a\nfake-image-bytes"


# =============================================================================
# Helper to build mock httpx response
# =============================================================================

def _mock_graphql_response(data: dict, status_code: int = 200):
    """Create a mock httpx response with a JSON body."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


# =============================================================================
# Tests: staged_upload_create
# =============================================================================

class TestStagedUploadCreate:
    """Test staged_upload_create GraphQL mutation."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Test successful staged upload creation."""
        graphql_resp = _mock_graphql_response({
            "data": {
                "stagedUploadsCreate": {
                    "stagedTargets": [{
                        "url": "https://shopify-upload.s3.amazonaws.com",
                        "resourceUrl": "https://storage.shopify.com/resource/abc",
                        "parameters": [
                            {"name": "key", "value": "upload/abc"},
                            {"name": "policy", "value": "encoded-policy"},
                        ],
                    }],
                    "userErrors": [],
                }
            }
        })

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=graphql_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await staged_upload_create(
                shop_domain="shop.myshopify.com",
                access_token="shpat_test",
                filename="product-refined.png",
                mime_type="image/png",
                file_size=1024,
            )

        assert result["url"] == "https://shopify-upload.s3.amazonaws.com"
        assert result["resourceUrl"] == "https://storage.shopify.com/resource/abc"
        assert len(result["parameters"]) == 2

    @pytest.mark.asyncio
    async def test_user_errors_raise(self):
        """Test that GraphQL user errors raise Exception."""
        graphql_resp = _mock_graphql_response({
            "data": {
                "stagedUploadsCreate": {
                    "stagedTargets": [],
                    "userErrors": [{"field": "input", "message": "Invalid file type"}],
                }
            }
        })

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=graphql_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(Exception, match="Invalid file type"):
                await staged_upload_create(
                    shop_domain="shop.myshopify.com",
                    access_token="shpat_test",
                    filename="bad.exe",
                    mime_type="application/octet-stream",
                    file_size=100,
                )

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """Test that non-200 HTTP status raises Exception."""
        graphql_resp = _mock_graphql_response({}, status_code=500)

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=graphql_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(Exception, match="stagedUploadsCreate failed"):
                await staged_upload_create(
                    shop_domain="shop.myshopify.com",
                    access_token="shpat_test",
                    filename="img.png",
                    mime_type="image/png",
                    file_size=100,
                )

    @pytest.mark.asyncio
    async def test_empty_targets_raises(self):
        """Test that empty stagedTargets raises Exception."""
        graphql_resp = _mock_graphql_response({
            "data": {
                "stagedUploadsCreate": {
                    "stagedTargets": [],
                    "userErrors": [],
                }
            }
        })

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=graphql_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(Exception, match="no staged targets"):
                await staged_upload_create(
                    shop_domain="shop.myshopify.com",
                    access_token="shpat_test",
                    filename="img.png",
                    mime_type="image/png",
                    file_size=100,
                )


# =============================================================================
# Tests: _upload_to_staged_target
# =============================================================================

class TestUploadToStagedTarget:
    """Test _upload_to_staged_target helper."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Test successful file upload to staged target."""
        resp = MagicMock()
        resp.status_code = 201

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await _upload_to_staged_target(
                upload_url="https://shopify-upload.s3.amazonaws.com",
                parameters=[{"name": "key", "value": "upload/abc"}],
                image_bytes=FAKE_IMAGE,
                filename="product.png",
                mime_type="image/png",
            )

        # Verify POST was called with correct URL
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://shopify-upload.s3.amazonaws.com"

    @pytest.mark.asyncio
    async def test_204_no_content_accepted(self):
        """Test that 204 No Content is a success status."""
        resp = MagicMock()
        resp.status_code = 204

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            # Should not raise
            await _upload_to_staged_target(
                upload_url="https://upload.example.com",
                parameters=[],
                image_bytes=FAKE_IMAGE,
                filename="img.png",
                mime_type="image/png",
            )

    @pytest.mark.asyncio
    async def test_400_raises(self):
        """Test that 400 status raises Exception."""
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad Request"

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(Exception, match="Staged upload file POST failed"):
                await _upload_to_staged_target(
                    upload_url="https://upload.example.com",
                    parameters=[],
                    image_bytes=FAKE_IMAGE,
                    filename="img.png",
                    mime_type="image/png",
                )


# =============================================================================
# Tests: file_create
# =============================================================================

class TestFileCreate:
    """Test file_create GraphQL mutation."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Test successful file creation in Shopify Media Library."""
        graphql_resp = _mock_graphql_response({
            "data": {
                "fileCreate": {
                    "files": [{
                        "id": "gid://shopify/MediaImage/123",
                        "alt": "Product visual",
                    }],
                    "userErrors": [],
                }
            }
        })

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=graphql_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            gid = await file_create(
                shop_domain="shop.myshopify.com",
                access_token="shpat_test",
                staged_resource_url="https://storage.shopify.com/resource/abc",
                alt_text="Product visual",
            )

        assert gid == "gid://shopify/MediaImage/123"

    @pytest.mark.asyncio
    async def test_user_errors_raise(self):
        """Test that user errors raise Exception."""
        graphql_resp = _mock_graphql_response({
            "data": {
                "fileCreate": {
                    "files": [],
                    "userErrors": [{"field": "files", "message": "Unsupported content type"}],
                }
            }
        })

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=graphql_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(Exception, match="Unsupported content type"):
                await file_create(
                    shop_domain="shop.myshopify.com",
                    access_token="shpat_test",
                    staged_resource_url="https://storage.shopify.com/resource/abc",
                )

    @pytest.mark.asyncio
    async def test_empty_files_raises(self):
        """Test that empty files list raises Exception."""
        graphql_resp = _mock_graphql_response({
            "data": {
                "fileCreate": {
                    "files": [],
                    "userErrors": [],
                }
            }
        })

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=graphql_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(Exception, match="fileCreate returned no files"):
                await file_create(
                    shop_domain="shop.myshopify.com",
                    access_token="shpat_test",
                    staged_resource_url="https://storage.shopify.com/resource/abc",
                )

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """Test non-200 HTTP status raises Exception."""
        graphql_resp = _mock_graphql_response({}, status_code=502)

        with patch("src.ecommerce.services.shopify_service.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=graphql_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(Exception, match="fileCreate failed"):
                await file_create(
                    shop_domain="shop.myshopify.com",
                    access_token="shpat_test",
                    staged_resource_url="https://storage.shopify.com/resource/abc",
                )


# =============================================================================
# Tests: upload_media_to_shopify (full orchestration)
# =============================================================================

class TestUploadMediaToShopify:
    """Test the full upload_media_to_shopify orchestrator."""

    @pytest.mark.asyncio
    async def test_happy_path_orchestration(self):
        """Test that all 3 steps are called in order."""
        with patch("src.ecommerce.services.shopify_service.staged_upload_create",
                    new_callable=AsyncMock, return_value={
                        "url": "https://upload.s3.amazonaws.com",
                        "parameters": [{"name": "key", "value": "abc"}],
                        "resourceUrl": "https://storage.shopify.com/resource/abc",
                    }) as mock_staged, \
             patch("src.ecommerce.services.shopify_service._upload_to_staged_target",
                    new_callable=AsyncMock) as mock_upload, \
             patch("src.ecommerce.services.shopify_service.file_create",
                    new_callable=AsyncMock,
                    return_value="gid://shopify/MediaImage/456") as mock_file:

            result = await upload_media_to_shopify(
                shop_domain="shop.myshopify.com",
                access_token="shpat_test",
                image_bytes=FAKE_IMAGE,
                filename="product-refined.png",
                alt_text="Refined product",
            )

        assert result == "gid://shopify/MediaImage/456"

        # staged_upload_create called with correct params
        mock_staged.assert_called_once()
        staged_kwargs = mock_staged.call_args.kwargs
        assert staged_kwargs["shop_domain"] == "shop.myshopify.com"
        assert staged_kwargs["filename"] == "product-refined.png"
        assert staged_kwargs["file_size"] == len(FAKE_IMAGE)

        # File uploaded to staged target
        mock_upload.assert_called_once()
        upload_kwargs = mock_upload.call_args.kwargs
        assert upload_kwargs["upload_url"] == "https://upload.s3.amazonaws.com"
        assert upload_kwargs["image_bytes"] == FAKE_IMAGE

        # file_create called with resource URL
        mock_file.assert_called_once()
        file_kwargs = mock_file.call_args.kwargs
        assert file_kwargs["staged_resource_url"] == "https://storage.shopify.com/resource/abc"
        assert file_kwargs["alt_text"] == "Refined product"

    @pytest.mark.asyncio
    async def test_staged_upload_failure_propagates(self):
        """Test that staged upload failure stops the flow."""
        with patch("src.ecommerce.services.shopify_service.staged_upload_create",
                    new_callable=AsyncMock,
                    side_effect=Exception("stagedUploadsCreate error")), \
             patch("src.ecommerce.services.shopify_service._upload_to_staged_target",
                    new_callable=AsyncMock) as mock_upload, \
             patch("src.ecommerce.services.shopify_service.file_create",
                    new_callable=AsyncMock) as mock_file:

            with pytest.raises(Exception, match="stagedUploadsCreate error"):
                await upload_media_to_shopify(
                    shop_domain="shop.myshopify.com",
                    access_token="shpat_test",
                    image_bytes=FAKE_IMAGE,
                    filename="img.png",
                )

        # Subsequent steps should NOT be called
        mock_upload.assert_not_called()
        mock_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_upload_failure_propagates(self):
        """Test that file upload (step 2) failure stops the flow."""
        with patch("src.ecommerce.services.shopify_service.staged_upload_create",
                    new_callable=AsyncMock, return_value={
                        "url": "https://upload.s3.amazonaws.com",
                        "parameters": [],
                        "resourceUrl": "https://storage.shopify.com/resource/abc",
                    }), \
             patch("src.ecommerce.services.shopify_service._upload_to_staged_target",
                    new_callable=AsyncMock,
                    side_effect=Exception("Upload POST failed")), \
             patch("src.ecommerce.services.shopify_service.file_create",
                    new_callable=AsyncMock) as mock_file:

            with pytest.raises(Exception, match="Upload POST failed"):
                await upload_media_to_shopify(
                    shop_domain="shop.myshopify.com",
                    access_token="shpat_test",
                    image_bytes=FAKE_IMAGE,
                    filename="img.png",
                )

        mock_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_mime_type(self):
        """Test default mime_type is image/png."""
        with patch("src.ecommerce.services.shopify_service.staged_upload_create",
                    new_callable=AsyncMock, return_value={
                        "url": "https://upload.example.com",
                        "parameters": [],
                        "resourceUrl": "https://storage.example.com",
                    }) as mock_staged, \
             patch("src.ecommerce.services.shopify_service._upload_to_staged_target",
                    new_callable=AsyncMock), \
             patch("src.ecommerce.services.shopify_service.file_create",
                    new_callable=AsyncMock, return_value="gid://1"):

            await upload_media_to_shopify(
                shop_domain="shop.myshopify.com",
                access_token="shpat_test",
                image_bytes=FAKE_IMAGE,
                filename="img.png",
            )

        assert mock_staged.call_args.kwargs["mime_type"] == "image/png"

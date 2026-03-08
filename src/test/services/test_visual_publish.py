"""
Unit tests for ShopifyPublishAdapter.publish_visual_assets.

Covers:
  - Happy path: all 3 assets published
  - Partial assets (only refined, no ad/hero)
  - Missing access_token skips all
  - Individual asset download failure continues with next
  - Individual upload failure continues with next
  - No visual_assets on state (empty dict / None)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.publish_adapters import ShopifyPublishAdapter
from src.ecommerce.state import MissionState

# Patch targets – publish_visual_assets does *local* imports so we patch at source
_HTTPX_ASYNC_CLIENT = "httpx.AsyncClient"
_UPLOAD_MEDIA = "src.ecommerce.services.shopify_service.upload_media_to_shopify"
_ADD_PRODUCT_IMAGE = "src.ecommerce.services.shopify_service.add_product_image"
_GET_BODY = "src.ecommerce.services.shopify_service.get_product_body"
_UPDATE_BODY = "src.ecommerce.services.shopify_service.update_product_body"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def adapter():
    return ShopifyPublishAdapter()


@pytest.fixture
def state_with_assets():
    state = MissionState(
        product_id="product-123",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"product_name": "Ceramic Bowl"},
        autonomous=True,
    )
    state.visual_assets = {
        "refined_url": "https://r2.example.com/visual/shop/m1/refined.png",
        "ad_url": "https://r2.example.com/visual/shop/m1/ad.png",
        "hero_url": "https://r2.example.com/visual/shop/m1/hero.png",
    }
    return state


@pytest.fixture
def creds():
    return {"access_token": "shpat_test_token"}


FAKE_IMAGE = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def _mock_httpx_client(response_content=FAKE_IMAGE, raise_for_status=None):
    """Helper to create a mock httpx async client context manager."""
    mock_response = MagicMock()
    mock_response.content = response_content
    if raise_for_status:
        mock_response.raise_for_status = MagicMock(side_effect=raise_for_status)
    else:
        mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# =============================================================================
# Tests: Happy path
# =============================================================================

class TestPublishVisualAssetsHappy:
    """Happy path tests."""

    @pytest.mark.asyncio
    async def test_publishes_all_three_assets(self, adapter, state_with_assets, creds):
        """All 3 assets should be published: refined via add_product_image, ad+hero via upload_media."""
        mock_client = _mock_httpx_client()

        with patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client), \
             patch(_UPLOAD_MEDIA, new_callable=AsyncMock,
                   return_value="gid://shopify/File/1") as mock_upload, \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock,
                   return_value="gid://shopify/MediaImage/1") as mock_add_img, \
             patch(_GET_BODY, new_callable=AsyncMock, return_value="<p>existing</p>"), \
             patch(_UPDATE_BODY, new_callable=AsyncMock):

            await adapter.publish_visual_assets(state_with_assets, creds)

        # Refined image goes through add_product_image
        assert mock_add_img.call_count == 1
        assert mock_add_img.call_args.kwargs["product_id"] == "product-123"
        assert "refined" in mock_add_img.call_args.kwargs["alt_text"]

        # Ad + hero go through upload_media_to_shopify
        assert mock_upload.call_count == 2
        filenames = [c.kwargs["filename"] for c in mock_upload.call_args_list]
        assert "Ceramic Bowl-ad.png" in filenames
        assert "Ceramic Bowl-hero.png" in filenames

    @pytest.mark.asyncio
    async def test_upload_params(self, adapter, state_with_assets, creds):
        """Verify correct params passed to upload_media_to_shopify for ad/hero."""
        mock_client = _mock_httpx_client()

        with patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client), \
             patch(_UPLOAD_MEDIA, new_callable=AsyncMock,
                   return_value="gid://shopify/File/1") as mock_upload, \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock,
                   return_value="gid://shopify/MediaImage/1") as mock_add_img, \
             patch(_GET_BODY, new_callable=AsyncMock, return_value="<p>existing</p>"), \
             patch(_UPDATE_BODY, new_callable=AsyncMock):

            await adapter.publish_visual_assets(state_with_assets, creds)

        # Refined goes through add_product_image
        assert mock_add_img.call_count == 1
        assert mock_add_img.call_args.kwargs["shop_domain"] == "shop.myshopify.com"
        assert mock_add_img.call_args.kwargs["access_token"] == "shpat_test_token"
        assert "refined" in mock_add_img.call_args.kwargs["alt_text"]

        # Ad/hero go through upload_media_to_shopify
        first_call = mock_upload.call_args_list[0]
        assert first_call.kwargs["shop_domain"] == "shop.myshopify.com"
        assert first_call.kwargs["access_token"] == "shpat_test_token"
        assert first_call.kwargs["image_bytes"] == FAKE_IMAGE
        assert "ad" in first_call.kwargs["alt_text"]


# =============================================================================
# Tests: Partial assets
# =============================================================================

class TestPublishVisualAssetsPartial:
    """Tests with partial asset availability."""

    @pytest.mark.asyncio
    async def test_only_refined_url(self, adapter, creds):
        """Only refined asset should go through add_product_image when others are None."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"product_name": "Bowl"},
        )
        state.visual_assets = {
            "refined_url": "https://r2/refined.png",
            "ad_url": None,
            "hero_url": None,
        }

        with patch(_UPLOAD_MEDIA, new_callable=AsyncMock,
                   return_value="gid://1") as mock_upload, \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock,
                   return_value="gid://shopify/MediaImage/1") as mock_add_img, \
             patch(_GET_BODY, new_callable=AsyncMock, return_value="<p>existing</p>"), \
             patch(_UPDATE_BODY, new_callable=AsyncMock):

            await adapter.publish_visual_assets(state, creds)

        # Refined goes through add_product_image, not upload_media
        assert mock_add_img.call_count == 1
        assert "refined" in mock_add_img.call_args.kwargs["alt_text"]
        mock_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_asset_urls(self, adapter, creds):
        """Empty string URLs should be skipped."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"product_name": "Bowl"},
        )
        state.visual_assets = {
            "refined_url": "",
            "ad_url": "",
            "hero_url": "",
        }

        with patch(_UPLOAD_MEDIA, new_callable=AsyncMock) as mock_upload, \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock) as mock_add_img:
            await adapter.publish_visual_assets(state, creds)

        mock_upload.assert_not_called()
        mock_add_img.assert_not_called()


# =============================================================================
# Tests: Missing credentials
# =============================================================================

class TestPublishVisualAssetsNoCreds:
    """Tests with missing or empty credentials."""

    @pytest.mark.asyncio
    async def test_no_access_token_skips(self, adapter, state_with_assets):
        """Should skip publishing when access_token is empty."""
        with patch(_UPLOAD_MEDIA, new_callable=AsyncMock) as mock_upload:
            await adapter.publish_visual_assets(state_with_assets, {"access_token": ""})

        mock_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_access_token_key(self, adapter, state_with_assets):
        """Should skip publishing when access_token key is missing."""
        with patch(_UPLOAD_MEDIA, new_callable=AsyncMock) as mock_upload:
            await adapter.publish_visual_assets(state_with_assets, {})

        mock_upload.assert_not_called()


# =============================================================================
# Tests: No visual_assets
# =============================================================================

class TestPublishVisualAssetsNone:
    """Tests when visual_assets is None or empty."""

    @pytest.mark.asyncio
    async def test_none_visual_assets(self, adapter, creds):
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )
        state.visual_assets = None

        # Should not raise
        await adapter.publish_visual_assets(state, creds)

    @pytest.mark.asyncio
    async def test_empty_dict_visual_assets(self, adapter, creds):
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )
        state.visual_assets = {}

        with patch(_UPLOAD_MEDIA, new_callable=AsyncMock) as mock_upload:
            await adapter.publish_visual_assets(state, creds)

        mock_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_visual_assets_attr(self, adapter, creds):
        """State with no visual_assets attribute at all."""
        state = MagicMock()
        state.visual_assets = None
        state.raw_input = {}
        state.shop_id = "shop.myshopify.com"

        await adapter.publish_visual_assets(state, creds)


# =============================================================================
# Tests: Failure paths
# =============================================================================

class TestPublishVisualAssetsFailure:
    """Failure path tests."""

    @pytest.mark.asyncio
    async def test_download_failure_continues(self, adapter, creds):
        """Download failure for one ad/hero asset should not stop others."""
        import httpx

        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"product_name": "Bowl"},
        )
        state.visual_assets = {
            "refined_url": "https://r2/refined.png",
            "ad_url": "https://r2/ad.png",
            "hero_url": "https://r2/hero.png",
        }

        call_idx = [0]

        mock_ok_response = MagicMock()
        mock_ok_response.content = FAKE_IMAGE
        mock_ok_response.raise_for_status = MagicMock()

        mock_bad_response = MagicMock()
        mock_bad_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
        )

        async def mock_get(url):
            call_idx[0] += 1
            if call_idx[0] == 1:  # first httpx call (ad) fails
                return mock_bad_response
            return mock_ok_response

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client), \
             patch(_UPLOAD_MEDIA, new_callable=AsyncMock,
                   return_value="gid://1") as mock_upload, \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock,
                   return_value="gid://shopify/MediaImage/1") as mock_add_img, \
             patch(_GET_BODY, new_callable=AsyncMock, return_value="<p>existing</p>"), \
             patch(_UPDATE_BODY, new_callable=AsyncMock):

            await adapter.publish_visual_assets(state, creds)

        # Refined goes through add_product_image (no httpx download)
        assert mock_add_img.call_count == 1
        # 1 successful upload (hero), ad download failed
        assert mock_upload.call_count == 1

    @pytest.mark.asyncio
    async def test_upload_failure_continues(self, adapter, state_with_assets, creds):
        """Upload failure for one asset should not stop others."""
        mock_client = _mock_httpx_client()
        upload_call_count = [0]

        async def flaky_upload(**kwargs):
            upload_call_count[0] += 1
            if upload_call_count[0] == 1:  # first upload (ad) fails
                raise Exception("Shopify API error")
            return "gid://shopify/File/ok"

        with patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client), \
             patch(_UPLOAD_MEDIA, side_effect=flaky_upload), \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock,
                   return_value="gid://shopify/MediaImage/1") as mock_add_img, \
             patch(_GET_BODY, new_callable=AsyncMock, return_value="<p>existing</p>"), \
             patch(_UPDATE_BODY, new_callable=AsyncMock):

            await adapter.publish_visual_assets(state_with_assets, creds)

        # Refined goes through add_product_image
        assert mock_add_img.call_count == 1
        # Both ad and hero were attempted via upload_media
        assert upload_call_count[0] == 2

    @pytest.mark.asyncio
    async def test_product_name_defaults_to_product(self, adapter, creds):
        """Default product_name when not in raw_input."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},  # no product_name
        )
        state.visual_assets = {"refined_url": "https://r2/img.png"}

        with patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock,
                   return_value="gid://shopify/MediaImage/1") as mock_add_img, \
             patch(_UPLOAD_MEDIA, new_callable=AsyncMock) as mock_upload, \
             patch(_GET_BODY, new_callable=AsyncMock, return_value="<p>existing</p>"), \
             patch(_UPDATE_BODY, new_callable=AsyncMock):

            await adapter.publish_visual_assets(state, creds)

        # Refined goes through add_product_image with default product name in alt_text
        assert mock_add_img.call_count == 1
        assert "product" in mock_add_img.call_args.kwargs["alt_text"]
        mock_upload.assert_not_called()

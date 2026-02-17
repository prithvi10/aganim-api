"""
Unit tests for VisualService -- fal.ai visual generation wrapper.

Covers:
  - Happy path for all 4 pipeline methods
  - Progress callback invocations
  - Edge cases (empty prompts, varied result shapes)
  - Failure paths (network errors, fal.ai errors, missing deps)
  - Static helpers (_extract_image_url, _build_ad_prompt)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from src.ecommerce.services.visual_service import VisualService


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def visual_svc():
    """Create a VisualService with a dummy key."""
    return VisualService(fal_key="test-fal-key")


@pytest.fixture
def progress_cb():
    """A mock progress callback."""
    return MagicMock()


FAKE_IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-data"
FAKE_MASKED_BYTES = b"\x89PNG\r\n\x1a\nfake-masked-data"


# =============================================================================
# Tests: _extract_image_url (static helper)
# =============================================================================

class TestExtractImageUrl:
    """Test _extract_image_url with various fal.ai result shapes."""

    def test_images_list_with_dict(self):
        result = {"images": [{"url": "https://fal.ai/img1.png"}]}
        assert VisualService._extract_image_url(result) == "https://fal.ai/img1.png"

    def test_images_list_with_string(self):
        result = {"images": ["https://fal.ai/img2.png"]}
        assert VisualService._extract_image_url(result) == "https://fal.ai/img2.png"

    def test_data_nested_images(self):
        result = {"data": {"images": [{"url": "https://fal.ai/nested.png"}]}}
        assert VisualService._extract_image_url(result) == "https://fal.ai/nested.png"

    def test_single_image_dict(self):
        result = {"image": {"url": "https://fal.ai/single.png"}}
        assert VisualService._extract_image_url(result) == "https://fal.ai/single.png"

    def test_single_image_string(self):
        result = {"image": "https://fal.ai/direct.png"}
        assert VisualService._extract_image_url(result) == "https://fal.ai/direct.png"

    def test_empty_images_list_raises(self):
        with pytest.raises(ValueError, match="Could not extract image URL"):
            VisualService._extract_image_url({"images": []})

    def test_no_image_keys_raises(self):
        with pytest.raises(ValueError, match="Could not extract image URL"):
            VisualService._extract_image_url({"status": "ok"})

    def test_none_input_raises(self):
        with pytest.raises(ValueError, match="Could not extract image URL"):
            VisualService._extract_image_url(None)

    def test_string_input_raises(self):
        with pytest.raises(ValueError, match="Could not extract image URL"):
            VisualService._extract_image_url("not a dict")

    def test_image_dict_with_empty_url(self):
        result = {"images": [{"url": ""}]}
        assert VisualService._extract_image_url(result) == ""


# =============================================================================
# Tests: _build_ad_prompt (static helper)
# =============================================================================

class TestBuildAdPrompt:
    """Test _build_ad_prompt with various inputs."""

    def test_with_hook_and_brand(self):
        prompt = VisualService._build_ad_prompt("New Collection", "MyBrand")
        assert "New Collection" in prompt
        assert "MyBrand" in prompt
        assert "Professional" in prompt

    def test_with_hook_only(self):
        prompt = VisualService._build_ad_prompt("Summer Sale", "")
        assert "Summer Sale" in prompt
        assert "brand name" not in prompt.lower() or "MyBrand" not in prompt

    def test_empty_hook(self):
        prompt = VisualService._build_ad_prompt("", "")
        assert "Professional" in prompt
        # Should NOT contain the Render text instruction
        assert 'Render the text ""' not in prompt

    def test_no_watermarks_instruction_present(self):
        prompt = VisualService._build_ad_prompt("Test", "")
        assert "No watermarks" in prompt


# =============================================================================
# Tests: isolate_product
# =============================================================================

class TestIsolateProduct:
    """Test isolate_product method."""

    @pytest.mark.asyncio
    async def test_happy_path(self, visual_svc, progress_cb):
        """Test successful product isolation with rembg."""
        mock_response = MagicMock()
        mock_response.content = FAKE_IMAGE_BYTES
        mock_response.raise_for_status = MagicMock()

        with patch("src.ecommerce.services.visual_service.httpx.AsyncClient") as mock_client_cls, \
             patch("src.ecommerce.services.visual_service._get_rembg") as mock_rembg_fn:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            mock_rembg_fn.return_value = lambda b: FAKE_MASKED_BYTES

            result = await visual_svc.isolate_product(
                image_url="https://cdn.shopify.com/product.jpg",
                progress=progress_cb,
            )

        assert result == FAKE_MASKED_BYTES
        # Progress should have been called 3 times: downloading, isolating, done
        assert progress_cb.call_count == 3
        progress_cb.assert_any_call("masking", 5, "Downloading product image...")
        progress_cb.assert_any_call("masking", 20, "Product isolated successfully")

    @pytest.mark.asyncio
    async def test_no_progress_callback(self, visual_svc):
        """Test isolate_product works without a progress callback."""
        mock_response = MagicMock()
        mock_response.content = FAKE_IMAGE_BYTES
        mock_response.raise_for_status = MagicMock()

        with patch("src.ecommerce.services.visual_service.httpx.AsyncClient") as mock_client_cls, \
             patch("src.ecommerce.services.visual_service._get_rembg") as mock_rembg_fn:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            mock_rembg_fn.return_value = lambda b: FAKE_MASKED_BYTES

            result = await visual_svc.isolate_product(
                image_url="https://cdn.shopify.com/product.jpg",
                progress=None,
            )

        assert result == FAKE_MASKED_BYTES

    @pytest.mark.asyncio
    async def test_download_http_error(self, visual_svc, progress_cb):
        """Test isolate_product raises on HTTP download error."""
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
        )

        with patch("src.ecommerce.services.visual_service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await visual_svc.isolate_product(
                    image_url="https://cdn.shopify.com/missing.jpg",
                    progress=progress_cb,
                )

    @pytest.mark.asyncio
    async def test_rembg_unavailable_returns_original_bytes(self, visual_svc):
        """Test isolate_product gracefully returns original image when rembg is unavailable."""
        mock_response = MagicMock()
        mock_response.content = FAKE_IMAGE_BYTES
        mock_response.raise_for_status = MagicMock()

        with patch("src.ecommerce.services.visual_service.httpx.AsyncClient") as mock_client_cls, \
             patch("src.ecommerce.services.visual_service._get_rembg", return_value=None):

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await visual_svc.isolate_product(
                image_url="https://cdn.shopify.com/product.jpg",
            )
            # Should return original image bytes (graceful fallback)
            assert result == FAKE_IMAGE_BYTES

    @pytest.mark.asyncio
    async def test_rembg_processing_error(self, visual_svc):
        """Test isolate_product propagates rembg runtime errors."""
        mock_response = MagicMock()
        mock_response.content = FAKE_IMAGE_BYTES
        mock_response.raise_for_status = MagicMock()

        def rembg_explodes(data):
            raise RuntimeError("Model failed to process image")

        with patch("src.ecommerce.services.visual_service.httpx.AsyncClient") as mock_client_cls, \
             patch("src.ecommerce.services.visual_service._get_rembg") as mock_rembg_fn:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            mock_rembg_fn.return_value = rembg_explodes

            with pytest.raises(RuntimeError, match="Model failed"):
                await visual_svc.isolate_product(
                    image_url="https://cdn.shopify.com/product.jpg",
                )


# =============================================================================
# Tests: refine_product
# =============================================================================

class TestRefineProduct:
    """Test refine_product method (Flux 2.0 Pro via fal.ai)."""

    @pytest.mark.asyncio
    async def test_happy_path(self, visual_svc, progress_cb):
        """Test successful background refinement using base64 data URI."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(return_value={
            "images": [{"url": "https://fal.ai/output/refined.png"}]
        })

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            result = await visual_svc.refine_product(
                masked_image_bytes=FAKE_MASKED_BYTES,
                brand_prompt="Minimalist Kyoto aesthetic",
                progress=progress_cb,
            )

        assert result == "https://fal.ai/output/refined.png"
        # upload is no longer called — image bytes are sent as a base64 data URI
        mock_fal.subscribe.assert_called_once()
        # Verify model used is Flux Pro
        call_args = mock_fal.subscribe.call_args
        assert call_args[0][0] == VisualService.FLUX_PRO_MODEL
        # Verify image_url is a data URI
        arguments = call_args[1]["arguments"] if "arguments" in (call_args[1] or {}) else call_args[0][1]
        assert arguments["image_url"].startswith("data:image/png;base64,")

        # Progress should have been called 4 times
        assert progress_cb.call_count == 4

    @pytest.mark.asyncio
    async def test_fal_client_import_error(self, visual_svc):
        """Test refine_product raises when fal_client is not installed."""
        with patch("src.ecommerce.services.visual_service._get_fal_client",
                    side_effect=ImportError("fal-client not found")):
            with pytest.raises(ImportError, match="fal-client"):
                await visual_svc.refine_product(
                    masked_image_bytes=FAKE_MASKED_BYTES,
                    brand_prompt="test",
                )

    @pytest.mark.asyncio
    async def test_fal_subscribe_error(self, visual_svc):
        """Test refine_product propagates fal.ai API errors."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(side_effect=Exception("fal.ai rate limited"))

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            with pytest.raises(Exception, match="rate limited"):
                await visual_svc.refine_product(
                    masked_image_bytes=FAKE_MASKED_BYTES,
                    brand_prompt="test",
                )

    @pytest.mark.asyncio
    async def test_fal_result_no_images(self, visual_svc):
        """Test refine_product raises ValueError for unexpected result format."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(return_value={"status": "done"})

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            with pytest.raises(ValueError, match="Could not extract image URL"):
                await visual_svc.refine_product(
                    masked_image_bytes=FAKE_MASKED_BYTES,
                    brand_prompt="test",
                )

    @pytest.mark.asyncio
    async def test_empty_brand_prompt(self, visual_svc):
        """Test refine_product works with an empty brand prompt."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(return_value={
            "images": [{"url": "https://fal.ai/out.png"}]
        })

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            result = await visual_svc.refine_product(
                masked_image_bytes=FAKE_MASKED_BYTES,
                brand_prompt="",
            )

        assert result == "https://fal.ai/out.png"
        # prompt should still be passed (just empty)
        call_args = mock_fal.subscribe.call_args
        assert call_args[1]["arguments"]["prompt"] == ""


# =============================================================================
# Tests: generate_ad
# =============================================================================

class TestGenerateAd:
    """Test generate_ad method (Ideogram 3.0 via fal.ai)."""

    @pytest.mark.asyncio
    async def test_happy_path(self, visual_svc, progress_cb):
        """Test successful ad generation with hook text and brand name."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(return_value={
            "images": [{"url": "https://fal.ai/ad.png"}]
        })

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            result = await visual_svc.generate_ad(
                refined_image_url="https://fal.ai/refined.png",
                hook_text="New Collection",
                brand_name="Kyoto Artisan",
                progress=progress_cb,
            )

        assert result == "https://fal.ai/ad.png"
        call_args = mock_fal.subscribe.call_args
        assert call_args[0][0] == VisualService.IDEOGRAM_MODEL
        assert "New Collection" in call_args[1]["arguments"]["prompt"]
        assert "Kyoto Artisan" in call_args[1]["arguments"]["prompt"]

        # Progress should be called 3 times
        assert progress_cb.call_count == 3

    @pytest.mark.asyncio
    async def test_no_brand_name(self, visual_svc):
        """Test ad generation without brand name."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(return_value={
            "images": [{"url": "https://fal.ai/ad.png"}]
        })

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            result = await visual_svc.generate_ad(
                refined_image_url="https://fal.ai/refined.png",
                hook_text="Summer Sale",
            )

        assert result == "https://fal.ai/ad.png"

    @pytest.mark.asyncio
    async def test_fal_error_propagates(self, visual_svc):
        """Test that fal.ai errors propagate through generate_ad."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(
            side_effect=TimeoutError("fal.ai generation timed out")
        )

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            with pytest.raises(TimeoutError, match="timed out"):
                await visual_svc.generate_ad(
                    refined_image_url="https://fal.ai/refined.png",
                    hook_text="Test",
                )


# =============================================================================
# Tests: expand_hero
# =============================================================================

class TestExpandHero:
    """Test expand_hero method (SD 3.5 outpainting via fal.ai)."""

    @pytest.mark.asyncio
    async def test_happy_path(self, visual_svc, progress_cb):
        """Test successful hero banner expansion."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(return_value={
            "images": [{"url": "https://fal.ai/hero.png"}]
        })

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            result = await visual_svc.expand_hero(
                refined_image_url="https://fal.ai/refined.png",
                brand_prompt="Zen garden aesthetic",
                progress=progress_cb,
            )

        assert result == "https://fal.ai/hero.png"
        call_args = mock_fal.subscribe.call_args
        assert call_args[0][0] == VisualService.SD35_OUTPAINT_MODEL
        # Verify 16:9 dimensions (1920x1080)
        assert call_args[1]["arguments"]["image_size"]["width"] == 1920
        assert call_args[1]["arguments"]["image_size"]["height"] == 1080
        # Brand prompt should be included
        assert "Zen garden aesthetic" in call_args[1]["arguments"]["prompt"]

        # Progress should be called 3 times
        assert progress_cb.call_count == 3

    @pytest.mark.asyncio
    async def test_no_brand_prompt(self, visual_svc):
        """Test hero expansion with empty brand prompt."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(return_value={
            "images": [{"url": "https://fal.ai/hero.png"}]
        })

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            result = await visual_svc.expand_hero(
                refined_image_url="https://fal.ai/refined.png",
            )

        assert result == "https://fal.ai/hero.png"
        call_args = mock_fal.subscribe.call_args
        prompt = call_args[1]["arguments"]["prompt"]
        assert "16:9" in prompt

    @pytest.mark.asyncio
    async def test_fal_error_propagates(self, visual_svc):
        """Test that fal.ai errors propagate through expand_hero."""
        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(
            side_effect=ConnectionError("fal.ai unreachable")
        )

        with patch("src.ecommerce.services.visual_service._get_fal_client", return_value=mock_fal):
            with pytest.raises(ConnectionError, match="unreachable"):
                await visual_svc.expand_hero(
                    refined_image_url="https://fal.ai/refined.png",
                )


# =============================================================================
# Tests: Constructor / env config
# =============================================================================

class TestVisualServiceConfig:
    """Test constructor and environment configuration."""

    def test_explicit_key(self):
        svc = VisualService(fal_key="explicit-key")
        assert svc._fal_key == "explicit-key"

    @patch.dict("os.environ", {"FAL_KEY": "env-key"})
    def test_env_key_fallback(self):
        svc = VisualService()
        assert svc._fal_key == "env-key"

    @patch.dict("os.environ", {}, clear=True)
    def test_no_key_defaults_empty(self):
        svc = VisualService()
        assert svc._fal_key == ""

    def test_key_written_to_env(self):
        with patch.dict("os.environ", {}, clear=True):
            VisualService(fal_key="written-key")
            import os
            assert os.environ.get("FAL_KEY") == "written-key"

    def test_model_endpoints_set(self):
        assert "flux-pro" in VisualService.FLUX_PRO_MODEL
        assert "ideogram" in VisualService.IDEOGRAM_MODEL
        assert "stable-diffusion" in VisualService.SD35_OUTPAINT_MODEL

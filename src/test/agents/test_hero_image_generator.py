"""
Unit tests for HeroImageGenerator -- Nano Banana text-to-image hero banner generation.

Covers:
  - generate: happy path, progress callbacks, error handling
  - _extract_url: various response shapes
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.services.hero_image_generator import (
    HeroImageGenerator,
    NANO_BANANA_T2I_MODEL,
)

_FAL_CLIENT = "src.ecommerce.services.visual_service._get_fal_client"
_HTTPX_ASYNC_CLIENT = "httpx.AsyncClient"

FAKE_IMAGE_BYTES = b"fake-hero-png-bytes"
FAKE_FAL_URL = "https://fal.media/files/hero-1234.png"


def _make_httpx_mock(response_content=FAKE_IMAGE_BYTES):
    mock_response = MagicMock()
    mock_response.content = response_content
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestHeroImageGeneratorConstants:
    def test_model_name(self):
        assert NANO_BANANA_T2I_MODEL == "fal-ai/nano-banana"


class TestExtractUrl:
    def test_images_list_with_dict(self):
        result = {"images": [{"url": FAKE_FAL_URL, "width": 1024}]}
        assert HeroImageGenerator._extract_url(result) == FAKE_FAL_URL

    def test_images_list_with_string(self):
        result = {"images": [FAKE_FAL_URL]}
        assert HeroImageGenerator._extract_url(result) == FAKE_FAL_URL

    def test_empty_images_raises(self):
        with pytest.raises(ValueError, match="Could not extract"):
            HeroImageGenerator._extract_url({"images": []})

    def test_no_images_key_raises(self):
        with pytest.raises(ValueError, match="Could not extract"):
            HeroImageGenerator._extract_url({"data": "something"})


class TestGenerate:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        fal_client = MagicMock()
        fal_client.subscribe = MagicMock(return_value={
            "images": [{"url": FAKE_FAL_URL}]
        })
        httpx_mock = _make_httpx_mock()

        with patch(_FAL_CLIENT, return_value=fal_client), \
             patch(_HTTPX_ASYNC_CLIENT, return_value=httpx_mock):
            gen = HeroImageGenerator()
            result = await gen.generate(prompt="Test hero prompt")

        assert result == FAKE_IMAGE_BYTES
        fal_client.subscribe.assert_called_once()
        call_args = fal_client.subscribe.call_args
        assert call_args[0][0] == NANO_BANANA_T2I_MODEL
        assert call_args[1]["arguments"]["prompt"] == "Test hero prompt"
        assert call_args[1]["arguments"]["aspect_ratio"] == "16:9"
        assert call_args[1]["arguments"]["num_images"] == 1

    @pytest.mark.asyncio
    async def test_custom_aspect_ratio(self):
        fal_client = MagicMock()
        fal_client.subscribe = MagicMock(return_value={
            "images": [{"url": FAKE_FAL_URL}]
        })
        httpx_mock = _make_httpx_mock()

        with patch(_FAL_CLIENT, return_value=fal_client), \
             patch(_HTTPX_ASYNC_CLIENT, return_value=httpx_mock):
            gen = HeroImageGenerator()
            await gen.generate(prompt="Test", aspect_ratio="1:1")

        call_args = fal_client.subscribe.call_args
        assert call_args[1]["arguments"]["aspect_ratio"] == "1:1"

    @pytest.mark.asyncio
    async def test_progress_callbacks(self):
        fal_client = MagicMock()
        fal_client.subscribe = MagicMock(return_value={
            "images": [{"url": FAKE_FAL_URL}]
        })
        httpx_mock = _make_httpx_mock()

        progress_calls = []
        def track_progress(phase, pct, label):
            progress_calls.append((phase, pct, label))

        with patch(_FAL_CLIENT, return_value=fal_client), \
             patch(_HTTPX_ASYNC_CLIENT, return_value=httpx_mock):
            gen = HeroImageGenerator()
            await gen.generate(prompt="Test", progress=track_progress)

        phases = [c[0] for c in progress_calls]
        assert "generating" in phases
        assert "complete" in phases

    @pytest.mark.asyncio
    async def test_fal_error_propagates(self):
        fal_client = MagicMock()
        fal_client.subscribe = MagicMock(side_effect=RuntimeError("fal.ai down"))

        with patch(_FAL_CLIENT, return_value=fal_client):
            gen = HeroImageGenerator()
            with pytest.raises(RuntimeError, match="fal.ai down"):
                await gen.generate(prompt="Test")

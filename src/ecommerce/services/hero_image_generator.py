"""
HeroImageGenerator -- Hero banner generation via Nano Banana.

Supports two modes:
  - Text-to-image (T2I): ``generate()`` -- no source image needed
  - Image-to-image (img2img): ``generate_from_image()`` -- blends a product
    reference image into a new thematic environment

Both modes produce 16:9 hero banners for blog posts, collections, and
hero sections.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

import httpx

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

ProgressCallback = Optional[Callable[[str, int, str], None]]

NANO_BANANA_T2I_MODEL = "fal-ai/nano-banana"
NANO_BANANA_EDIT_MODEL = "fal-ai/nano-banana/edit"


class HeroImageGenerator:
    """Generate hero banner images via Nano Banana T2I or img2img.

    Usage::

        gen = HeroImageGenerator()

        # Mode 1: Text-to-image (theme background, no product image)
        png_bytes = await gen.generate(prompt="...")

        # Mode 2: Image-to-image (product blend)
        png_bytes = await gen.generate_from_image(
            image_url="https://cdn.shopify.com/product.jpg",
            prompt="...",
        )
    """

    # ------------------------------------------------------------------
    # Mode 1: Text-to-image
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        progress: ProgressCallback = None,
    ) -> bytes:
        """Generate a hero banner from a text prompt and return image bytes."""
        logger.info("[HeroImageGenerator] T2I prompt: %s", prompt[:300])

        if progress:
            progress("generating", 20, "Generating hero banner...")

        result_bytes = await self._nano_banana_t2i(prompt, aspect_ratio, progress)

        if progress:
            progress("complete", 90, "Hero banner ready")

        logger.info("[HeroImageGenerator] T2I complete bytes=%d", len(result_bytes))
        return result_bytes

    # ------------------------------------------------------------------
    # Mode 2: Image-to-image (product blend)
    # ------------------------------------------------------------------

    async def generate_from_image(
        self,
        image_url: str,
        prompt: str,
        aspect_ratio: str = "16:9",
        progress: ProgressCallback = None,
    ) -> bytes:
        """Blend a product reference image into a themed hero banner."""
        logger.info(
            "[HeroImageGenerator] img2img prompt: %s  image: %s",
            prompt[:200], image_url[:120],
        )

        if progress:
            progress("generating", 20, "Blending product into hero banner...")

        result_bytes = await self._nano_banana_edit(
            image_url, prompt, aspect_ratio, progress,
        )

        if progress:
            progress("complete", 90, "Hero banner ready")

        logger.info("[HeroImageGenerator] img2img complete bytes=%d", len(result_bytes))
        return result_bytes

    # ------------------------------------------------------------------
    # Internal: fal.ai calls
    # ------------------------------------------------------------------

    async def _nano_banana_t2i(
        self,
        prompt: str,
        aspect_ratio: str,
        progress: ProgressCallback = None,
    ) -> bytes:
        from src.ecommerce.services.visual_service import _get_fal_client

        fal_client = _get_fal_client()

        result = await asyncio.to_thread(
            fal_client.subscribe,
            NANO_BANANA_T2I_MODEL,
            arguments={
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "num_images": 1,
                "safety_tolerance": "6",
            },
        )

        url = self._extract_url(result)

        if progress:
            progress("generating", 70, "Downloading hero image...")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    async def _nano_banana_edit(
        self,
        image_url: str,
        prompt: str,
        aspect_ratio: str,
        progress: ProgressCallback = None,
    ) -> bytes:
        from src.ecommerce.services.visual_service import _get_fal_client

        fal_client = _get_fal_client()

        result = await asyncio.to_thread(
            fal_client.subscribe,
            NANO_BANANA_EDIT_MODEL,
            arguments={
                "image_urls": [image_url],
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "num_images": 1,
            },
        )

        url = self._extract_url(result)

        if progress:
            progress("generating", 70, "Downloading hero image...")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    @staticmethod
    def _extract_url(result: dict) -> str:
        if isinstance(result, dict):
            images = result.get("images", [])
            if images:
                first = images[0]
                if isinstance(first, dict):
                    return first.get("url", "")
                return str(first)
            image = result.get("image")
            if isinstance(image, dict):
                return image.get("url", "")
            if isinstance(image, str):
                return image
        raise ValueError(
            f"Could not extract image URL from Nano Banana result: {result}"
        )

"""
HeroImageGenerator -- Hero banner generation via Nano Banana text-to-image.

Generates 16:9 hero banners for blog posts, collections, and hero sections
using fal-ai/nano-banana (text-to-image). No source image is needed.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

import httpx

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

ProgressCallback = Optional[Callable[[str, int, str], None]]

NANO_BANANA_T2I_MODEL = "fal-ai/nano-banana"


class HeroImageGenerator:
    """Generate a hero banner image using Nano Banana text-to-image.

    Usage::

        gen = HeroImageGenerator()
        png_bytes = await gen.generate(
            prompt="Wide hero banner for a sake collection...",
            aspect_ratio="16:9",
        )
    """

    async def generate(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        progress: ProgressCallback = None,
    ) -> bytes:
        """Generate a hero banner from a text prompt and return image bytes."""
        logger.info("[HeroImageGenerator] prompt: %s", prompt[:300])

        if progress:
            progress("generating", 20, "Generating hero banner...")

        result_bytes = await self._nano_banana_t2i(prompt, aspect_ratio, progress)

        if progress:
            progress("complete", 90, "Hero banner ready")

        logger.info("[HeroImageGenerator] complete bytes=%d", len(result_bytes))
        return result_bytes

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

    @staticmethod
    def _extract_url(result: dict) -> str:
        if isinstance(result, dict):
            images = result.get("images", [])
            if images:
                first = images[0]
                if isinstance(first, dict):
                    return first.get("url", "")
                return str(first)
        raise ValueError(
            f"Could not extract image URL from Nano Banana T2I result: {result}"
        )

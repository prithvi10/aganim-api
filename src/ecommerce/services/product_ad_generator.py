"""
ProductAdGenerator -- Marketing ad generation via Nano Banana (Google Imagen).

Sends the merchant's product image as a reference to fal-ai/nano-banana/edit
and generates a high-quality marketing scene around it.

The product is NOT pre-processed (no isolation, compositing, or masking).
Nano Banana handles scene generation natively from the reference image.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

import httpx

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

ProgressCallback = Optional[Callable[[str, int, str], None]]

NANO_BANANA_EDIT_MODEL = "fal-ai/nano-banana/edit"


class ProductAdGenerator:
    """Generate a marketing ad image using Nano Banana /edit.

    Usage::

        gen = ProductAdGenerator()
        png_bytes = await gen.generate(
            image_url="https://cdn.shopify.com/product.jpg",
            product_name="Yuzu Sake",
            progress=progress_cb,
        )
    """

    async def generate(
        self,
        image_url: str,
        product_name: str = "",
        brand_soul: str = "",
        use_brand_style: bool = False,
        progress: ProgressCallback = None,
    ) -> bytes:
        """Send the product image to Nano Banana /edit and return the result."""
        from src.ecommerce.agents.visual.prompts import build_nano_banana_prompt

        if progress:
            progress("generating", 10, "Building marketing prompt...")

        prompt = build_nano_banana_prompt(
            product_name=product_name,
            brand_soul=brand_soul if use_brand_style else "",
        )
        logger.info("[ProductAdGenerator] prompt: %s", prompt[:300])

        if progress:
            progress("generating", 20, "Generating marketing ad...")

        result_bytes = await self._nano_banana_edit(image_url, prompt, progress)

        if progress:
            progress("complete", 90, "Ad image ready")

        logger.info(
            "[ProductAdGenerator] complete product=%s bytes=%d",
            product_name or "(unnamed)",
            len(result_bytes),
        )
        return result_bytes

    async def _nano_banana_edit(
        self,
        image_url: str,
        prompt: str,
        progress: ProgressCallback = None,
    ) -> bytes:
        """Call fal-ai/nano-banana/edit and return the image as bytes."""
        from src.ecommerce.services.visual_service import _get_fal_client

        fal_client = _get_fal_client()

        result = await asyncio.to_thread(
            fal_client.subscribe,
            NANO_BANANA_EDIT_MODEL,
            arguments={
                "image_urls": [image_url],
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "num_images": 1,
            },
        )

        url = self._extract_url(result)

        if progress:
            progress("generating", 70, "Downloading generated image...")

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

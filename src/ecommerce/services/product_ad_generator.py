"""
ProductAdGenerator -- End-to-end pixel-perfect marketing ad pipeline.

Orchestrates:
  1. Product isolation (BiRefNet / rembg via VisualService)
  2. Object splitting (connected-components on alpha)
  3. Auto-layout (1-6 objects)
  4. Canvas compositing + mask generation
  5. Flux Fill inpainting (background / props only; products are mask-protected)
  6. PIL text overlay (product name)
  7. R2 upload

The product pixels are NEVER redrawn -- only the background is generated.
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Callable, List, Optional, Tuple, Union

import httpx

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

ProgressCallback = Optional[Callable[[str, int, str], None]]

FLUX_FILL_MODEL = "fal-ai/flux-pro/v1/fill"


class ProductAdGenerator:
    """Generate a single production-safe marketing ad image.

    Usage::

        gen = ProductAdGenerator()
        png_bytes = await gen.generate(
            image_url="https://cdn.shopify.com/product.jpg",
            ad_style="ingredients",
            product_name="Yuzu Sake",
            product_type="Beverage",
            tags=["sake", "citrus"],
            brand_soul="Japanese minimalism...",
            progress=progress_cb,
        )
    """

    def __init__(self, canvas_size: int = 1024):
        self.canvas_size = canvas_size

    async def generate(
        self,
        image_url: str,
        ad_style: str = "aesthetic",
        product_name: str = "",
        product_type: str = "",
        tags: Optional[List[str]] = None,
        brand_soul: str = "",
        progress: ProgressCallback = None,
    ) -> bytes:
        """Run the full ad generation pipeline and return final PNG bytes."""
        from src.ecommerce.services.visual_service import VisualService
        from src.ecommerce.services.visual_layout import (
            split_objects,
            auto_layout,
            composite_and_mask,
        )
        from src.ecommerce.agents.visual.prompts import build_styled_background_prompt

        visual_svc = VisualService()

        # -- Phase 1: Isolate product -----------------------------------------
        if progress:
            progress("masking", 5, "Isolating product from background...")
        isolated_bytes = await visual_svc.isolate_product(
            image_url=image_url, progress=progress,
        )

        # -- Phase 2: Split into individual objects ----------------------------
        if progress:
            progress("splitting", 20, "Detecting individual products...")
        cutouts = split_objects(isolated_bytes)
        logger.info(
            "[ProductAdGenerator] split complete: %d object(s)", len(cutouts),
        )
        if progress:
            progress("splitting", 25, f"Found {len(cutouts)} product(s)")

        # -- Phase 3: Auto-layout ----------------------------------------------
        if progress:
            progress("layout", 30, "Computing product arrangement...")
        slots = auto_layout(cutouts, self.canvas_size)

        # -- Phase 4: Composite + mask -----------------------------------------
        if progress:
            progress("compositing", 35, "Compositing products on canvas...")
        canvas_bytes, mask_bytes = composite_and_mask(
            cutouts, slots, self.canvas_size,
        )

        # -- Phase 5: Flux Fill inpainting -------------------------------------
        if progress:
            progress("inpainting", 40, f"Generating {ad_style} background & props...")

        prompt = build_styled_background_prompt(
            ad_style=ad_style,
            brand_soul=brand_soul,
            product_name=product_name,
            product_type=product_type,
            tags=tags,
        )
        logger.info("[ProductAdGenerator] inpaint prompt: %s", prompt[:300])

        inpainted_bytes = await self._flux_fill(
            canvas_bytes, mask_bytes, prompt, progress,
        )

        # -- Phase 6: PIL text overlay -----------------------------------------
        if product_name:
            if progress:
                progress("text_overlay", 80, "Adding product name...")
            final_bytes = self._overlay_product_name(inpainted_bytes, product_name)
        else:
            final_bytes = inpainted_bytes

        if progress:
            progress("complete", 90, "Ad image ready")

        logger.info(
            "[ProductAdGenerator] pipeline complete style=%s objects=%d bytes=%d",
            ad_style, len(cutouts), len(final_bytes),
        )
        return final_bytes

    # ------------------------------------------------------------------
    # Flux Fill call
    # ------------------------------------------------------------------

    async def _flux_fill(
        self,
        image_bytes: bytes,
        mask_bytes: bytes,
        prompt: str,
        progress: ProgressCallback = None,
    ) -> bytes:
        """Call fal-ai/flux-pro/v1/fill and return the result as PNG bytes."""
        from src.ecommerce.services.visual_service import _get_fal_client

        fal_client = _get_fal_client()

        img_b64 = base64.b64encode(image_bytes).decode()
        mask_b64 = base64.b64encode(mask_bytes).decode()

        result = await asyncio.to_thread(
            fal_client.subscribe,
            FLUX_FILL_MODEL,
            arguments={
                "image_url": f"data:image/png;base64,{img_b64}",
                "mask_url": f"data:image/png;base64,{mask_b64}",
                "prompt": prompt,
                "num_images": 1,
                "image_size": {
                    "width": self.canvas_size,
                    "height": self.canvas_size,
                },
            },
        )

        fill_url = self._extract_url(result)

        if fill_url.startswith("data:"):
            if progress:
                progress("inpainting", 70, "Decoding inpainted image...")
            header, encoded = fill_url.split(",", 1)
            return base64.b64decode(encoded)

        if progress:
            progress("inpainting", 70, "Downloading inpainted image...")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(fill_url)
            resp.raise_for_status()
            return resp.content

    # ------------------------------------------------------------------
    # PIL text overlay
    # ------------------------------------------------------------------

    @staticmethod
    def _overlay_product_name(
        image_bytes: bytes,
        product_name: str,
        canvas_size: int = 1024,
    ) -> bytes:
        from PIL import Image as PILImage, ImageDraw, ImageFont

        img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)
        font_size = max(28, canvas_size // 20)

        font: Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]
        for path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "arial.ttf",
        ]:
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except (OSError, IOError):
                continue
        else:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), product_name, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (img.width - text_w) // 2
        y = img.height - text_h - max(30, canvas_size // 20)

        shadow_offset = max(2, font_size // 20)
        draw.text(
            (x + shadow_offset, y + shadow_offset),
            product_name, fill=(0, 0, 0, 180), font=font,
        )
        draw.text((x, y), product_name, fill=(255, 255, 255), font=font)

        out_buf = io.BytesIO()
        img.save(out_buf, "PNG")
        return out_buf.getvalue()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        raise ValueError(f"Could not extract image URL from Flux Fill result: {result}")

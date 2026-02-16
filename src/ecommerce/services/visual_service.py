"""
VisualService -- Unified wrapper for fal.ai image generation models.

Provides three visual pipelines for the Pro-Visual mission step:
1. Product Isolation + Background Refinement (rembg + Flux 2.0 Pro inpainting)
2. Marketing Ad Generation with Typography (Ideogram 3.0)
3. Hero Banner Outpainting (Stable Diffusion 3.5)

All methods are async and accept an optional ``progress_callback`` so the
calling agent can push granular SSE updates to the frontend.

Required env vars:
    FAL_KEY          -- fal.ai API key
"""

from __future__ import annotations

import asyncio
import io
import os
import re
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

# Type alias for the progress callback used by SSE streaming
ProgressCallback = Optional[Callable[[str, int, str], None]]

# ---------------------------------------------------------------------------
# Input URL Validation — SSRF prevention
# ---------------------------------------------------------------------------

# Trusted hostname patterns for product images
_ALLOWED_IMAGE_HOSTS: Tuple[str, ...] = (
    "cdn.shopify.com",
    "cdn.shopifycdn.net",
    # Shopify per-store CDNs: {shop-name}.myshopify.com/cdn/...
)

# Regex for per-store Shopify CDN subdomains
_SHOPIFY_STORE_CDN_RE = re.compile(
    r"^[a-z0-9][a-z0-9\-]*\.myshopify\.com$", re.IGNORECASE
)

# Allowed image extensions
_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}


class ImageURLValidationError(ValueError):
    """Raised when an image URL fails security validation."""
    pass


def validate_image_url(url: str, *, allow_fal_media: bool = False) -> str:
    """
    Validate that an image URL is from a trusted source before sending it
    to fal.ai models.  This prevents SSRF (Server-Side Request Forgery)
    where an attacker could pass ``http://169.254.169.254/latest/meta-data``
    or an internal-network URL as the product image.

    Args:
        url: The image URL to validate.
        allow_fal_media: If True, also allow ``fal.media`` and
            ``storage.googleapis.com/fal-*`` URLs (used for intermediate
            pipeline results that come back from fal.ai).

    Returns:
        The validated URL (stripped of whitespace).

    Raises:
        ImageURLValidationError: If the URL fails validation.
    """
    if not url or not isinstance(url, str):
        raise ImageURLValidationError("Image URL is empty or not a string")

    url = url.strip()

    # Must be HTTPS (block http://, ftp://, file://, data:, etc.)
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ImageURLValidationError(
            f"Image URL must use HTTPS (got {parsed.scheme!r})"
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise ImageURLValidationError("Image URL has no hostname")

    # Check against the allow-list
    is_trusted = False

    # 1. Exact-match trusted hosts
    if host in _ALLOWED_IMAGE_HOSTS:
        is_trusted = True

    # 2. Per-store Shopify CDN (e.g. my-store.myshopify.com)
    elif _SHOPIFY_STORE_CDN_RE.match(host):
        is_trusted = True

    # 3. fal.ai media URLs (only allowed for intermediate pipeline results)
    elif allow_fal_media and (
        host == "fal.media"
        or host.endswith(".fal.media")
        or (host.endswith(".googleapis.com") and "/fal-" in parsed.path)
    ):
        is_trusted = True

    if not is_trusted:
        raise ImageURLValidationError(
            f"Image URL host {host!r} is not in the trusted allow-list. "
            "Only Shopify CDN URLs are accepted."
        )

    # Validate the file extension (loose — query params are fine)
    path_lower = parsed.path.lower()
    if not any(path_lower.endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        raise ImageURLValidationError(
            f"Image URL path does not end with a recognised image extension "
            f"({', '.join(sorted(_ALLOWED_EXTENSIONS))})"
        )

    return url

# ---------------------------------------------------------------------------
# Lazy imports -- heavy deps loaded only when actually called
# ---------------------------------------------------------------------------

def _get_fal_client():
    """Lazily import and return the fal_client module."""
    try:
        import fal_client
        return fal_client
    except ImportError:
        raise ImportError(
            "fal-client is required for the visual pipeline. "
            "Install it with: pip install fal-client"
        )


def _get_rembg():
    """Lazily import rembg for background removal."""
    try:
        from rembg import remove as rembg_remove
        return rembg_remove
    except ImportError:
        raise ImportError(
            "rembg is required for product isolation. "
            "Install it with: pip install rembg"
        )


def _get_pil():
    """Lazily import Pillow."""
    try:
        from PIL import Image
        return Image
    except ImportError:
        raise ImportError(
            "Pillow is required for the visual pipeline. "
            "Install it with: pip install Pillow"
        )


class VisualService:
    """
    Unified visual generation service backed by fal.ai and rembg.

    Usage::

        svc = VisualService()
        mask_bytes = await svc.isolate_product(image_url, progress_cb)
        refined_url = await svc.refine_product(mask_bytes, brand_prompt, progress_cb)
        ad_url = await svc.generate_ad(refined_url, hook_text, progress_cb)
        hero_url = await svc.expand_hero(refined_url, progress_cb)
    """

    # fal.ai model endpoints
    FLUX_PRO_MODEL = "fal-ai/flux-pro/v1.1/redux"
    IDEOGRAM_MODEL = "fal-ai/ideogram/v3"
    SD35_OUTPAINT_MODEL = "fal-ai/stable-diffusion-v35-large"

    def __init__(self, fal_key: str | None = None):
        self._fal_key = fal_key or os.getenv("FAL_KEY", "")
        if self._fal_key:
            os.environ["FAL_KEY"] = self._fal_key

    # ------------------------------------------------------------------
    # 1. Product Isolation (rembg background removal)
    # ------------------------------------------------------------------

    async def isolate_product(
        self,
        image_url: str,
        progress: ProgressCallback = None,
    ) -> bytes:
        """
        Download the product image and remove the background using rembg.

        Returns:
            PNG bytes with transparent background (RGBA).
        """
        if progress:
            progress("masking", 5, "Downloading product image...")

        # Download image
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            input_bytes = resp.content

        if progress:
            progress("masking", 10, "Isolating product from background...")

        # rembg is CPU-bound -- run in executor to avoid blocking the event loop
        rembg_remove = _get_rembg()
        loop = asyncio.get_running_loop()
        output_bytes: bytes = await loop.run_in_executor(
            None, rembg_remove, input_bytes
        )

        if progress:
            progress("masking", 20, "Product isolated successfully")

        logger.info(
            "[VisualService] isolate_product complete input=%d bytes output=%d bytes",
            len(input_bytes),
            len(output_bytes),
        )
        return output_bytes

    # ------------------------------------------------------------------
    # 2. Background Refinement (Flux 2.0 Pro via fal.ai)
    # ------------------------------------------------------------------

    async def refine_product(
        self,
        masked_image_bytes: bytes,
        brand_prompt: str,
        progress: ProgressCallback = None,
    ) -> str:
        """
        Use Flux 2.0 Pro inpainting to regenerate the background behind the
        isolated product, guided by the Brand Soul prompt.

        Args:
            masked_image_bytes: RGBA PNG bytes from ``isolate_product``.
            brand_prompt: Text describing desired background style derived
                          from Brand Soul context.

        Returns:
            URL of the refined product image (hosted on fal.ai CDN).
        """
        if progress:
            progress("inpainting", 25, "Preparing brand-aligned background prompt...")

        fal_client = _get_fal_client()

        # Upload the masked image to fal storage for use as input
        if progress:
            progress("inpainting", 30, "Uploading isolated product to generation engine...")

        masked_url = await asyncio.to_thread(
            fal_client.upload,
            masked_image_bytes,
            "image/png",
        )

        if progress:
            progress("inpainting", 35, "Regenerating background with brand styling...")

        # Call Flux 2.0 Pro with the masked image + brand prompt
        result = await asyncio.to_thread(
            fal_client.subscribe,
            self.FLUX_PRO_MODEL,
            arguments={
                "image_url": masked_url,
                "prompt": brand_prompt,
                "num_images": 1,
                "image_size": "square_hd",
                "enable_safety_checker": True,
            },
        )

        image_url = self._extract_image_url(result)

        if progress:
            progress("inpainting", 50, "Background refinement complete")

        logger.info("[VisualService] refine_product complete url=%s", image_url)
        return image_url

    # ------------------------------------------------------------------
    # 3. Marketing Ad Generation (Ideogram 3.0 via fal.ai)
    # ------------------------------------------------------------------

    async def generate_ad(
        self,
        refined_image_url: str,
        hook_text: str,
        brand_name: str = "",
        progress: ProgressCallback = None,
    ) -> str:
        """
        Use Ideogram 3.0 to generate a marketing ad with high-fidelity
        typography rendered directly onto the image.

        Args:
            refined_image_url: URL of the refined product image.
            hook_text: Social media hook text to render on the ad
                       (e.g., "New Collection" or "Artisan Made").
            brand_name: Brand name for additional context.

        Returns:
            URL of the generated ad image.
        """
        if progress:
            progress("ad_generation", 55, "Composing marketing ad layout...")

        fal_client = _get_fal_client()

        # Build the ad prompt with typography instructions
        ad_prompt = self._build_ad_prompt(hook_text, brand_name)

        if progress:
            progress("ad_generation", 60, "Rendering typography and ad creative...")

        result = await asyncio.to_thread(
            fal_client.subscribe,
            self.IDEOGRAM_MODEL,
            arguments={
                "prompt": ad_prompt,
                "image_url": refined_image_url,
                "aspect_ratio": "1:1",
                "style_type": "DESIGN",
                "negative_prompt": "blurry, low quality, distorted text, misspelled",
            },
        )

        image_url = self._extract_image_url(result)

        if progress:
            progress("ad_generation", 70, "Marketing ad generated")

        logger.info("[VisualService] generate_ad complete url=%s", image_url)
        return image_url

    # ------------------------------------------------------------------
    # 4. Hero Banner Outpainting (SD 3.5 via fal.ai)
    # ------------------------------------------------------------------

    async def expand_hero(
        self,
        refined_image_url: str,
        brand_prompt: str = "",
        progress: ProgressCallback = None,
    ) -> str:
        """
        Use Stable Diffusion 3.5 outpainting to expand a product shot
        into a 16:9 hero banner suitable for blog pages and collection headers.

        Args:
            refined_image_url: URL of the refined product image.
            brand_prompt: Optional brand context for the expanded area.

        Returns:
            URL of the 16:9 hero banner image.
        """
        if progress:
            progress("outpainting", 75, "Preparing hero banner expansion...")

        fal_client = _get_fal_client()

        hero_prompt = (
            f"Expand this product photo into a wide 16:9 hero banner. "
            f"Maintain the product in the center, extend the background "
            f"seamlessly with consistent lighting and style. "
            f"{brand_prompt}"
        ).strip()

        if progress:
            progress("outpainting", 80, "Expanding to 16:9 hero banner...")

        result = await asyncio.to_thread(
            fal_client.subscribe,
            self.SD35_OUTPAINT_MODEL,
            arguments={
                "prompt": hero_prompt,
                "image_url": refined_image_url,
                "image_size": {
                    "width": 1920,
                    "height": 1080,
                },
                "num_images": 1,
                "enable_safety_checker": True,
            },
        )

        image_url = self._extract_image_url(result)

        if progress:
            progress("outpainting", 90, "Hero banner generated")

        logger.info("[VisualService] expand_hero complete url=%s", image_url)
        return image_url

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_image_url(result: Any) -> str:
        """Extract the first image URL from a fal.ai result dict."""
        if isinstance(result, dict):
            images = result.get("images") or result.get("data", {}).get("images", [])
            if images and isinstance(images, list):
                first = images[0]
                if isinstance(first, dict):
                    return first.get("url", "")
                return str(first)
            # Some models return a single "image" key
            image = result.get("image")
            if isinstance(image, dict):
                return image.get("url", "")
            if isinstance(image, str):
                return image
        raise ValueError(f"Could not extract image URL from fal.ai result: {result}")

    @staticmethod
    def _build_ad_prompt(hook_text: str, brand_name: str = "") -> str:
        """Build the Ideogram prompt for ad generation with typography."""
        parts = [
            "Professional social media marketing advertisement.",
            "Clean, modern design with product prominently featured.",
        ]
        if hook_text:
            parts.append(
                f'Render the text "{hook_text}" in bold, elegant typography '
                f"that is clearly legible and well-positioned."
            )
        if brand_name:
            parts.append(
                f'Include subtle brand name "{brand_name}" in a smaller font.'
            )
        parts.append(
            "High-fidelity, print-ready quality. No watermarks. "
            "Professional lighting and composition."
        )
        return " ".join(parts)

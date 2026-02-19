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
import base64
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


def _get_r2_public_host() -> str:
    """Extract the hostname from R2_PUBLIC_URL for allow-listing."""
    r2_url = os.getenv("R2_PUBLIC_URL", "")
    if r2_url:
        parsed = urlparse(r2_url.strip().rstrip("/"))
        return (parsed.hostname or "").lower()
    return ""


def validate_image_url(
    url: str,
    *,
    allow_fal_media: bool = False,
    allow_r2: bool = False,
) -> str:
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
        allow_r2: If True, also allow URLs hosted on the R2_PUBLIC_URL
            domain (used for custom-uploaded product images).

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

    # 4. R2 storage URLs (custom-uploaded product images)
    elif allow_r2:
        r2_host = _get_r2_public_host()
        if r2_host and host == r2_host:
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
    """Lazily import rembg for background removal.

    Returns the ``rembg.remove`` function, or *None* if the dependency
    is missing or disabled.

    rembg + onnxruntime loads the U2NET model (~170 MB) into RAM.  On
    memory-constrained hosts (e.g. Render free/starter 512 MB) this causes
    an OOM kill.  Set ``REMBG_ENABLED=true`` to opt-in; when the variable
    is absent or any other value rembg is **skipped** and the original
    image is sent directly to Flux Pro.
    """
    if not os.getenv("REMBG_ENABLED", "").lower() == "true":
        logger.info(
            "[VisualService] rembg disabled (set REMBG_ENABLED=true to enable "
            "background removal — requires ~512 MB free RAM)"
        )
        return None
    try:
        from rembg import remove as rembg_remove
        return rembg_remove
    except (ImportError, SystemExit):
        logger.warning(
            "[VisualService] rembg/onnxruntime not available — "
            "product isolation will be skipped (original image sent to Flux directly)"
        )
        return None


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
    FLUX_FILL_MODEL = "fal-ai/flux-pro/v1/fill"
    IDEOGRAM_MODEL = "fal-ai/ideogram/v3"
    SD35_OUTPAINT_MODEL = "fal-ai/stable-diffusion-v35-large"
    OUTPAINT_V2_MODEL = "fal-ai/image-apps-v2/outpaint"
    TEXT_REMOVAL_MODEL = "fal-ai/image-editing/text-removal"
    BIREFNET_MODEL = "fal-ai/birefnet/v2"
    OBJECT_REMOVAL_MODEL = "fal-ai/object-removal"

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

        If rembg/onnxruntime is not installed the original image bytes are
        returned so the rest of the pipeline (Flux inpainting) can still run.

        Returns:
            PNG bytes — with transparent background (RGBA) when rembg is
            available, otherwise the original image bytes.
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

        if rembg_remove is None:
            # Cloud fallback: use fal-ai/birefnet for background removal
            if progress:
                progress("masking", 12, "Using cloud background removal (BiRefNet)...")
            try:
                fal_client = _get_fal_client()
                b64 = base64.b64encode(input_bytes).decode()
                image_data_uri = f"data:image/png;base64,{b64}"
                result = await asyncio.to_thread(
                    fal_client.subscribe,
                    self.BIREFNET_MODEL,
                    arguments={
                        "image_url": image_data_uri,
                        "output_format": "png",
                    },
                )
                bg_removed_url = self._extract_image_url(result)
                async with httpx.AsyncClient(timeout=30) as dl:
                    resp2 = await dl.get(bg_removed_url)
                    resp2.raise_for_status()
                    output_bytes = resp2.content
                if progress:
                    progress("masking", 20, "Product isolated via cloud service")
                logger.info(
                    "[VisualService] isolate_product (birefnet) complete input=%d bytes output=%d bytes",
                    len(input_bytes), len(output_bytes),
                )
                return output_bytes
            except Exception as e:
                logger.warning(
                    "[VisualService] birefnet fallback failed, using original image: %s", e,
                )
                if progress:
                    progress("masking", 20, "Background removal unavailable — using original image")
                return input_bytes

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
    # 1b. Text Removal (fal.ai text-removal model)
    # ------------------------------------------------------------------

    async def remove_text(
        self,
        image_bytes: bytes,
        progress: ProgressCallback = None,
    ) -> bytes:
        """
        Remove all text overlays, logos, and watermarks from an image
        using the dedicated fal.ai text-removal model.

        Returns:
            Cleaned PNG image bytes with text removed.
        """
        if progress:
            progress("text_removal", 15, "Removing text overlays from image...")

        fal_client = _get_fal_client()

        b64 = base64.b64encode(image_bytes).decode()
        image_data_uri = f"data:image/png;base64,{b64}"

        result = await asyncio.to_thread(
            fal_client.subscribe,
            self.TEXT_REMOVAL_MODEL,
            arguments={
                "image_url": image_data_uri,
                "output_format": "png",
            },
        )

        cleaned_url = self._extract_image_url(result)

        if progress:
            progress("text_removal", 22, "Text removal complete — downloading cleaned image...")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(cleaned_url)
            resp.raise_for_status()
            cleaned_bytes = resp.content

        logger.info(
            "[VisualService] remove_text complete input=%d bytes output=%d bytes",
            len(image_bytes),
            len(cleaned_bytes),
        )
        return cleaned_bytes

    # ------------------------------------------------------------------
    # 1c. Object Removal — second-pass cleanup (Florence-2 + SAM2)
    # ------------------------------------------------------------------

    async def remove_objects(
        self,
        image_bytes: bytes,
        progress: ProgressCallback = None,
    ) -> bytes:
        """
        Remove remaining text, logos, and watermarks using the
        Florence-2 + SAM2 based object-removal model.

        This is a surgical second pass after the dedicated text-removal
        model to catch stylized text and fragments it missed.
        """
        if progress:
            progress("object_removal", 22, "Detecting remaining text and logos...")

        fal_client = _get_fal_client()

        b64 = base64.b64encode(image_bytes).decode()
        image_data_uri = f"data:image/png;base64,{b64}"

        result = await asyncio.to_thread(
            fal_client.subscribe,
            self.OBJECT_REMOVAL_MODEL,
            arguments={
                "image_url": image_data_uri,
                "prompt": "text, writing, watermark, logo",
            },
        )

        cleaned_url = self._extract_image_url(result)

        if progress:
            progress("object_removal", 25, "Object removal complete — downloading result...")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(cleaned_url)
            resp.raise_for_status()
            cleaned_bytes = resp.content

        logger.info(
            "[VisualService] remove_objects complete input=%d bytes output=%d bytes",
            len(image_bytes), len(cleaned_bytes),
        )
        return cleaned_bytes

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

        # Encode as base64 data URI — avoids needing fal storage upload perms
        if progress:
            progress("inpainting", 30, "Encoding isolated product for generation engine...")

        b64 = base64.b64encode(masked_image_bytes).decode()
        image_data_uri = f"data:image/png;base64,{b64}"

        if progress:
            progress("inpainting", 35, "Regenerating background with brand styling...")

        # Call Flux 2.0 Pro with the masked image + brand prompt
        result = await asyncio.to_thread(
            fal_client.subscribe,
            self.FLUX_PRO_MODEL,
            arguments={
                "image_url": image_data_uri,
                "prompt": brand_prompt,
                "num_images": 1,
                "image_size": "square_hd",
            },
        )

        image_url = self._extract_image_url(result)

        if progress:
            progress("inpainting", 50, "Background refinement complete")

        logger.info("[VisualService] refine_product complete url=%s", image_url)
        return image_url

    # ------------------------------------------------------------------
    # 2b. Style-aware Background Refinement (Marketing Studio)
    # ------------------------------------------------------------------

    async def refine_product_styled(
        self,
        masked_image_bytes: bytes,
        ad_style: str = "aesthetic",
        product_name: str = "",
        brand_soul: str = "",
        progress: ProgressCallback = None,
    ) -> str:
        """
        Use Flux 2.0 Pro Redux to regenerate the background behind the
        isolated product using a style-specific prompt.

        Uses the same proven approach as ``refine_product``: the masked
        RGBA image (transparent background) is sent as a base64 data URI
        to Flux Redux, which uses it as a reference and regenerates the
        background guided by the styled prompt.

        Args:
            masked_image_bytes: RGBA PNG bytes from ``isolate_product``.
            ad_style: Style key from AD_STYLE_PROMPTS.
            product_name: Product name for prompt context.
            brand_soul: Brand Soul text for aesthetic alignment.

        Returns:
            URL of the styled product image (hosted on fal.ai CDN).
        """
        from src.ecommerce.agents.visual.prompts import build_styled_background_prompt

        if progress:
            progress("inpainting", 25, f"Preparing {ad_style} styled background...")

        fal_client = _get_fal_client()

        styled_prompt = build_styled_background_prompt(
            ad_style=ad_style,
            product_name=product_name,
            brand_soul=brand_soul,
        )

        if progress:
            progress("inpainting", 30, "Encoding isolated product for styled generation...")

        b64 = base64.b64encode(masked_image_bytes).decode()
        image_data_uri = f"data:image/png;base64,{b64}"

        if progress:
            progress("inpainting", 35, f"Generating {ad_style} background...")

        result = await asyncio.to_thread(
            fal_client.subscribe,
            self.FLUX_PRO_MODEL,
            arguments={
                "image_url": image_data_uri,
                "prompt": styled_prompt,
                "num_images": 1,
                "image_size": "square_hd",
            },
        )

        image_url = self._extract_image_url(result)

        if progress:
            progress("inpainting", 50, "Styled background complete")

        logger.info(
            "[VisualService] refine_product_styled style=%s url=%s",
            ad_style, image_url,
        )
        return image_url

    # ------------------------------------------------------------------
    # 3. Marketing Ad Generation (Ideogram 3.0 via fal.ai)
    # ------------------------------------------------------------------

    async def generate_ad(
        self,
        refined_image_url: str,
        hook_text: str,
        brand_name: str = "",
        product_name: str = "",
        progress: ProgressCallback = None,
        prestyled: bool = False,
    ) -> str:
        """
        Use Ideogram 3.0 to generate a marketing ad with high-fidelity
        typography rendered directly onto the image.

        Args:
            refined_image_url: URL of the refined product image.
            hook_text: Social media hook text to render on the ad
                       (e.g., "New Collection" or "Artisan Made").
            brand_name: Brand name for additional context.
            product_name: Product name for context (avoids misidentification).
            prestyled: If True, the image already has a styled background
                       from ``refine_product_styled`` -- prompt focuses on
                       typography only.

        Returns:
            URL of the generated ad image.
        """
        if progress:
            progress("ad_generation", 55, "Composing marketing ad layout...")

        fal_client = _get_fal_client()

        clean_hook = self._clean_hook_text(hook_text)
        ad_prompt = self._build_ad_prompt(
            clean_hook, brand_name, product_name, prestyled=prestyled,
        )

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
                "negative_prompt": (
                    "blurry, low quality, distorted text, misspelled words, "
                    "hashtags, social media captions, watermark, "
                    "random text, gibberish, extra text, additional text, "
                    "unwanted text, placeholder text, decorative text, lorem ipsum, "
                    "different product, wrong product, altered product, redrawn product, "
                    "changed packaging, modified label, wrong number of items"
                ),
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
        Use fal.ai outpaint-v2 to expand a product shot into a 16:9 hero
        banner suitable for blog pages and collection headers.

        Args:
            refined_image_url: URL of the refined product image.
            brand_prompt: Optional brand context for the expanded area.

        Returns:
            URL of the 16:9 hero banner image.
        """
        if progress:
            progress("outpainting", 75, "Preparing hero banner expansion...")

        fal_client = _get_fal_client()

        _FAL_OUTPAINT_PROMPT_LIMIT = 500
        prompt = brand_prompt or (
            "Seamless product scene with consistent lighting and style. "
            "No text, no words, no logos, no writing. Purely visual."
        )
        if len(prompt) > _FAL_OUTPAINT_PROMPT_LIMIT:
            prompt = prompt[: _FAL_OUTPAINT_PROMPT_LIMIT - 3] + "..."

        if progress:
            progress("outpainting", 80, "Expanding to 16:9 hero banner...")

        result = await asyncio.to_thread(
            fal_client.subscribe,
            self.OUTPAINT_V2_MODEL,
            arguments={
                "image_url": refined_image_url,
                "expand_left": 400,
                "expand_right": 400,
                "expand_top": 0,
                "expand_bottom": 0,
                "zoom_out_percentage": 15,
                "prompt": prompt,
                "num_images": 1,
                "enable_safety_checker": True,
                "output_format": "png",
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
    def _clean_hook_text(raw_hook: str) -> str:
        """Extract only the headline from a social hook, stripping hashtags and filler."""
        import re

        lines = raw_hook.strip().splitlines()
        clean_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Skip lines that are predominantly hashtags
            if re.match(r"^[#\s\w]*#\w", stripped) and stripped.count("#") >= 2:
                continue
            # Remove inline hashtags
            stripped = re.sub(r"#\w+", "", stripped).strip()
            if stripped:
                clean_lines.append(stripped)

        headline = " ".join(clean_lines).strip()
        # Final cleanup: collapse whitespace, remove trailing punctuation duplication
        headline = re.sub(r"\s{2,}", " ", headline)
        return headline

    @staticmethod
    def _build_ad_prompt(
        hook_text: str,
        brand_name: str = "",
        product_name: str = "",
        prestyled: bool = False,
    ) -> str:
        """Build the Ideogram prompt for ad generation with typography.

        When ``prestyled=True`` the input image already has a styled background
        from ``refine_product_styled``, so the prompt focuses on adding
        typography without altering the product or scene.
        """
        product_desc = f" for {product_name}" if product_name else ""

        if prestyled:
            parts = [
                f"Social media marketing advertisement{product_desc}.",
                "The product photo and styled background in the reference image are FINAL.",
                "PRESERVE the reference image EXACTLY as-is — same product, same background, same composition, same colors.",
                "Do NOT replace, redraw, reinterpret, or alter the product or scene in any way.",
                "ONLY overlay bold, legible marketing typography onto the existing photograph.",
            ]
        else:
            parts = [
                f"Professional social media marketing advertisement{product_desc}.",
                "Clean, modern design with the actual product prominently featured.",
                "Keep the product IDENTICAL to the reference image — same shape, color, label, packaging, and count.",
                "Do NOT replace or reinterpret the product. Reproduce it faithfully.",
            ]

        text_lines: list[str] = []
        if product_name:
            text_lines.append(product_name)
        if hook_text:
            text_lines.append(hook_text)

        if text_lines:
            combined = '" and "'.join(text_lines)
            parts.append(
                f'Render the text "{combined}" in bold, elegant typography '
                f"that is clearly legible and well-positioned."
            )
            parts.append(
                "Spell every word correctly -- double-check spelling before rendering. "
                "Do NOT misspell, abbreviate, or alter the provided text in any way. "
                "Render the text exactly as provided, character for character. "
                "The ONLY text in the entire image must be the specified text above. "
                "Do NOT add any other words, letters, numbers, hashtags, captions, "
                "random text, or writing of any kind anywhere in the image."
            )
        if brand_name:
            parts.append(
                f'Include subtle brand name "{brand_name}" in a smaller font.'
            )
        parts.append(
            "High-fidelity, print-ready quality. No watermarks. "
            "No hashtags. No social media captions. No random or decorative text. "
            "Professional lighting and composition."
        )
        return " ".join(parts)

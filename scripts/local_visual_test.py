#!/usr/bin/env python3
"""
Local Visual Pipeline Test — Real fal.ai calls, local storage (no Cloudflare).

Tests the VisualService image generation pipeline end-to-end:
  1. Product Isolation (rembg background removal)
  2. Background Refinement (Flux 2.0 Pro via fal.ai)
  3. Marketing Ad Generation (Ideogram 3.0 via fal.ai)
  4. Hero Banner Outpainting (SD 3.5 via fal.ai)

All generated images are saved to  tmp/visual_local_test/<run_id>/

Prerequisites:
  pip install fal-client rembg Pillow httpx

Usage:
  # Run full pipeline with default test product
  FAL_KEY=your-key python scripts/local_visual_test.py

  # Run with a custom image URL (must be publicly accessible)
  FAL_KEY=your-key python scripts/local_visual_test.py --image-url "https://cdn.shopify.com/..."

  # Run only specific steps
  FAL_KEY=your-key python scripts/local_visual_test.py --steps mask,refine

  # Use a built-in test case
  FAL_KEY=your-key python scripts/local_visual_test.py --case ceramic-bowl

  # List all built-in test cases
  python scripts/local_visual_test.py --list-cases
"""

from __future__ import annotations

import argparse
import asyncio
import os
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# ── Fix macOS SSL certificates (Homebrew / standalone Python) ────────────────
# On macOS, Homebrew Python's OpenSSL often can't find the system CA bundle.
# Strategy: (1) truststore → use native macOS Keychain, (2) certifi fallback.
_ssl_fixed = False
try:
    import truststore
    truststore.inject_into_ssl()
    _ssl_fixed = True
except Exception:
    pass  # truststore not available or not supported

if not _ssl_fixed:
  try:
    import certifi
    _CA_BUNDLE = certifi.where()

    # 1. Env vars honoured by urllib3, requests, curl, and OpenSSL
    os.environ["SSL_CERT_FILE"] = _CA_BUNDLE
    os.environ["REQUESTS_CA_BUNDLE"] = _CA_BUNDLE
    os.environ["CURL_CA_BUNDLE"] = _CA_BUNDLE

    # 2. Monkey-patch stdlib ssl so *any* library that calls
    #    ssl.create_default_context() picks up the right CA bundle.
    _orig_create_default_context = ssl.create_default_context

    def _patched_create_default_context(
        purpose=ssl.Purpose.SERVER_AUTH, *, cafile=None, capath=None, cadata=None
    ):
        ctx = _orig_create_default_context(purpose, cafile=cafile, capath=capath, cadata=cadata)
        # Load certifi certs on top of whatever was loaded
        ctx.load_verify_locations(cafile=_CA_BUNDLE)
        return ctx

    ssl.create_default_context = _patched_create_default_context
    ssl._create_default_https_context = _patched_create_default_context

    # 3. Patch httpx (used by fal-client) — force its SSL context to use certifi
    try:
        import httpx
        _certifi_ctx = ssl.create_default_context(cafile=_CA_BUNDLE)
        httpx._config.DEFAULT_CERTS = _CA_BUNDLE  # type: ignore[attr-defined]
    except Exception:
        pass

  except ImportError:
    pass  # certifi not installed — rely on system certs

# Ensure project root is on sys.path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Auto-enable rembg for local testing (server defaults to disabled to avoid OOM)
if not os.getenv("REMBG_ENABLED"):
    os.environ["REMBG_ENABLED"] = "true"


# =============================================================================
# Built-in Test Cases — Product descriptions with sample Shopify CDN images
# =============================================================================

# Shopify Hydrogen demo store product image (publicly accessible)
_HYDROGEN_CDN = "https://cdn.shopify.com/s/files/1/0551/4566/0472/products"

TEST_CASES: Dict[str, Dict[str, Any]] = {
    "ceramic-bowl": {
        "product_name": "Handcrafted Ceramic Bowl — Kintsugi Collection",
        "brand_name": "Koto-gama",
        "brand_soul": (
            "Traditional Japanese craftsmanship rooted in 'Yo-no-bi' — beauty in "
            "everyday use. Wabi-sabi aesthetics with earthy clay tones, organic forms, "
            "and subtle gold-repair accents. Warm, natural lighting. Minimalist zen-inspired "
            "presentation on raw linen or weathered wood surfaces."
        ),
        "hook_text": "Artisan Made",
        # Hydrogen demo store — confirmed accessible
        "image_url": f"{_HYDROGEN_CDN}/Main_b13ad453-477c-4ed1-9b43-81f3345adfd6.jpg",
        "description": (
            "A hand-thrown stoneware bowl from the Kintsugi Collection. Each piece is "
            "unique, fired in a wood-burning kiln at 1280°C. Gold-lacquer repairs "
            "celebrate the beauty of imperfection. 15cm diameter, food-safe glaze."
        ),
    },
    "leather-bag": {
        "product_name": "Voyager Weekender — Full Grain Leather",
        "brand_name": "Atlas & Co.",
        "brand_soul": (
            "Heritage craftsmanship meets modern minimalism. Vegetable-tanned full-grain "
            "leather that develops a rich patina over time. Muted earth tones — saddle brown, "
            "cognac, charcoal. Clean studio photography on concrete or slate backgrounds. "
            "Travel-inspired lifestyle brand for the discerning modern explorer."
        ),
        "hook_text": "New Collection",
        "image_url": f"{_HYDROGEN_CDN}/Main_b13ad453-477c-4ed1-9b43-81f3345adfd6.jpg",
        "description": (
            "Full-grain vegetable-tanned leather weekender bag. Hand-stitched with "
            "waxed thread. Solid brass hardware. Cotton twill lining. "
            "Dimensions: 55cm × 30cm × 25cm. Ages beautifully."
        ),
    },
    "candle": {
        "product_name": "Midnight Garden Soy Candle — 250g",
        "brand_name": "Lumière",
        "brand_soul": (
            "French-inspired artisanal home fragrance. Soft, moody lighting with "
            "deep jewel tones — midnight blue, burgundy, forest green. Minimalist glass "
            "vessels on dark marble. Romantic, luxurious ambiance. Hand-poured in small "
            "batches. Typography is serif, elegant, understated."
        ),
        "hook_text": "Limited Edition",
        "image_url": f"{_HYDROGEN_CDN}/Main_b13ad453-477c-4ed1-9b43-81f3345adfd6.jpg",
        "description": (
            "Hand-poured soy wax candle with notes of jasmine, black fig, and "
            "cedarwood. 250g / 8.8oz. Burns for 45+ hours. Reusable glass vessel. "
            "Cotton wick. No synthetic fragrances."
        ),
    },
    "sneaker": {
        "product_name": "Urban Runner V2 — Cloud White",
        "brand_name": "Stride Labs",
        "brand_soul": (
            "Performance meets streetwear. Bold, energetic visuals with neon accents "
            "on clean white backgrounds. Dynamic angles, motion blur hints. Targeting "
            "Gen-Z urban athletes. Photography is crisp, high-contrast, editorial."
        ),
        "hook_text": "Just Dropped",
        "image_url": f"{_HYDROGEN_CDN}/Main_b13ad453-477c-4ed1-9b43-81f3345adfd6.jpg",
        "description": (
            "Lightweight running sneaker with responsive CloudFoam midsole. "
            "Breathable knit upper. 3M reflective heel tab. Rubber outsole with "
            "multi-surface grip. Sizes 6-13. Unisex."
        ),
    },
}


# =============================================================================
# Colour helpers for terminal output
# =============================================================================

class _C:
    """ANSI colour codes."""
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    RED    = "\033[91m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"


def _banner(msg: str) -> None:
    print(f"\n{_C.BOLD}{_C.CYAN}{'━' * 60}")
    print(f"  {msg}")
    print(f"{'━' * 60}{_C.RESET}\n")


def _step(msg: str) -> None:
    print(f"  {_C.GREEN}▸{_C.RESET} {msg}")


def _info(msg: str) -> None:
    print(f"  {_C.DIM}{msg}{_C.RESET}")


def _warn(msg: str) -> None:
    print(f"  {_C.YELLOW}⚠ {msg}{_C.RESET}")


def _err(msg: str) -> None:
    print(f"  {_C.RED}✘ {msg}{_C.RESET}")


def _ok(msg: str) -> None:
    print(f"  {_C.GREEN}✔ {msg}{_C.RESET}")


# =============================================================================
# Progress callback for SSE-style logging
# =============================================================================

def _progress(phase: str, pct: int, label: str) -> None:
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"    {_C.DIM}[{bar}] {pct:>3}% {phase:<16} {label}{_C.RESET}")


# =============================================================================
# Local storage helper
# =============================================================================

def _save_local(data: bytes, out_dir: Path, name: str) -> Path:
    """Save image bytes to the output directory."""
    path = out_dir / name
    path.write_bytes(data)
    size_kb = len(data) / 1024
    _ok(f"Saved {name}  ({size_kb:.1f} KB)")
    return path


async def _download(url: str) -> bytes:
    """Download an image URL and return bytes."""
    import httpx
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


# =============================================================================
# Sample image generator (no external deps needed)
# =============================================================================

def generate_sample_image(out_path: Path, label: str = "PRODUCT") -> Path:
    """
    Create a simple 800x800 product-like test image using Pillow.
    Draws a coloured circle (product) on a busy background so rembg
    has something meaningful to isolate.
    """
    from PIL import Image, ImageDraw, ImageFont

    W, H = 800, 800
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    # Gradient background (beige → warm grey)
    for y in range(H):
        r = int(210 + (y / H) * 30)
        g = int(195 + (y / H) * 20)
        b = int(170 + (y / H) * 15)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # "Table" surface — lower third
    for y in range(int(H * 0.65), H):
        grey = int(120 + (y - H * 0.65) / (H * 0.35) * 40)
        draw.line([(0, y), (W, y)], fill=(grey, grey - 10, grey - 20))

    # "Product" — a bowl-like ellipse
    cx, cy = W // 2, int(H * 0.50)
    rx, ry = 180, 120
    draw.ellipse(
        [cx - rx, cy - ry, cx + rx, cy + ry],
        fill=(139, 90, 43),
        outline=(100, 65, 30),
        width=4,
    )
    # Highlight
    draw.ellipse(
        [cx - rx + 30, cy - ry + 20, cx + rx - 30, cy - ry + 60],
        fill=(180, 130, 80),
    )
    # Inner shadow
    draw.ellipse(
        [cx - rx + 50, cy - 20, cx + rx - 50, cy + 50],
        fill=(110, 70, 35),
    )

    # Label
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
    except Exception:
        font = ImageFont.load_default()
    draw.text((20, 20), f"TEST: {label}", fill=(80, 80, 80), font=font)
    draw.text((20, H - 50), "local_visual_test.py sample", fill=(160, 160, 160), font=font)

    img.save(out_path, "PNG")
    return out_path


# =============================================================================
# Pipeline steps
# =============================================================================

async def step_mask(
    svc: Any,
    image_url: str,
    out_dir: Path,
    local_image_bytes: Optional[bytes] = None,
) -> Optional[bytes]:
    """Step 1: Product isolation (rembg background removal)."""
    _banner("Step 1 / 4 — Product Isolation (rembg)")

    if local_image_bytes:
        _step(f"Source: local image ({len(local_image_bytes) / 1024:.1f} KB)")
        _info("Running rembg on local image bytes...")
    else:
        _step(f"Source image: {image_url}")
        _info("Downloading and removing background...")

    t0 = time.time()
    try:
        if local_image_bytes:
            # Bypass URL download — run rembg directly on local bytes
            import asyncio as _aio
            rembg_remove = None
            try:
                from rembg import remove as rembg_remove
            except ImportError:
                _err("rembg not installed: pip install rembg")
                return None

            if _progress:
                _progress("masking", 10, "Isolating product from background...")

            loop = _aio.get_running_loop()
            masked_bytes = await loop.run_in_executor(None, rembg_remove, local_image_bytes)

            if _progress:
                _progress("masking", 20, "Product isolated successfully")
        else:
            masked_bytes = await svc.isolate_product(image_url, progress=_progress)
    except Exception as e:
        _err(f"Product isolation FAILED: {e}")
        return None

    elapsed = time.time() - t0
    _save_local(masked_bytes, out_dir, "01_masked_product.png")
    _ok(f"Product isolation complete in {elapsed:.1f}s")
    return masked_bytes


async def step_refine(
    svc: Any,
    masked_bytes: bytes,
    brand_prompt: str,
    out_dir: Path,
) -> Optional[str]:
    """Step 2: Background refinement (Flux 2.0 Pro via fal.ai)."""
    _banner("Step 2 / 4 — Background Refinement (Flux 2.0 Pro)")
    _info(f"Brand prompt: {brand_prompt[:120]}...")

    t0 = time.time()
    try:
        refined_url = await svc.refine_product(
            masked_image_bytes=masked_bytes,
            brand_prompt=brand_prompt,
            progress=_progress,
        )
    except Exception as e:
        _err(f"Background refinement FAILED: {e}")
        return None

    elapsed = time.time() - t0
    _step(f"fal.ai result URL: {refined_url}")

    # Download and save locally
    try:
        refined_bytes = await _download(refined_url)
        _save_local(refined_bytes, out_dir, "02_refined_product.png")
    except Exception as e:
        _warn(f"Could not download refined image: {e}")

    _ok(f"Background refinement complete in {elapsed:.1f}s")
    return refined_url


async def step_ad(
    svc: Any,
    refined_url: str,
    hook_text: str,
    brand_name: str,
    out_dir: Path,
) -> Optional[str]:
    """Step 3: Marketing ad generation (Ideogram 3.0 via fal.ai)."""
    _banner("Step 3 / 4 — Marketing Ad (Ideogram 3.0)")
    _info(f"Hook text: \"{hook_text}\"")
    _info(f"Brand: {brand_name or '(none)'}")

    t0 = time.time()
    try:
        ad_url = await svc.generate_ad(
            refined_image_url=refined_url,
            hook_text=hook_text,
            brand_name=brand_name,
            progress=_progress,
        )
    except Exception as e:
        _err(f"Ad generation FAILED: {e}")
        return None

    elapsed = time.time() - t0
    _step(f"fal.ai result URL: {ad_url}")

    try:
        ad_bytes = await _download(ad_url)
        _save_local(ad_bytes, out_dir, "03_marketing_ad.png")
    except Exception as e:
        _warn(f"Could not download ad image: {e}")

    _ok(f"Ad generation complete in {elapsed:.1f}s")
    return ad_url


async def step_hero(
    svc: Any,
    refined_url: str,
    hero_prompt: str,
    out_dir: Path,
) -> Optional[str]:
    """Step 4: Hero banner outpainting (SD 3.5 via fal.ai)."""
    _banner("Step 4 / 4 — Hero Banner (SD 3.5 Outpaint)")
    _info(f"Hero prompt: {hero_prompt[:120]}...")

    t0 = time.time()
    try:
        hero_url = await svc.expand_hero(
            refined_image_url=refined_url,
            brand_prompt=hero_prompt,
            progress=_progress,
        )
    except Exception as e:
        _err(f"Hero expansion FAILED: {e}")
        return None

    elapsed = time.time() - t0
    _step(f"fal.ai result URL: {hero_url}")

    try:
        hero_bytes = await _download(hero_url)
        _save_local(hero_bytes, out_dir, "04_hero_banner.png")
    except Exception as e:
        _warn(f"Could not download hero banner: {e}")

    _ok(f"Hero expansion complete in {elapsed:.1f}s")
    return hero_url


# =============================================================================
# Main pipeline runner
# =============================================================================

async def run_pipeline(args: argparse.Namespace) -> None:
    from src.ecommerce.services.visual_service import VisualService
    from src.ecommerce.agents.visual.prompts import build_inpaint_prompt, build_hero_prompt

    # Resolve test case
    if args.case:
        case = TEST_CASES.get(args.case)
        if not case:
            _err(f"Unknown test case: {args.case}")
            _info(f"Available: {', '.join(TEST_CASES)}")
            return
    else:
        case = {
            "product_name": args.product_name or "Test Product",
            "brand_name": args.brand_name or "",
            "brand_soul": args.brand_soul or "",
            "hook_text": args.hook_text or "New Collection",
            "image_url": args.image_url or "",
            "description": args.description or "",
        }

    # Handle --local-image: read file bytes, skip URL download for masking
    local_image_bytes: Optional[bytes] = None
    local_image_path: Optional[Path] = None

    if getattr(args, "local_image", None):
        local_image_path = Path(args.local_image)
        if not local_image_path.exists():
            _err(f"Local image not found: {local_image_path}")
            return
        local_image_bytes = local_image_path.read_bytes()
        _ok(f"Loaded local image: {local_image_path} ({len(local_image_bytes) / 1024:.1f} KB)")

    # Handle --generate-sample: create a test image with Pillow
    if getattr(args, "generate_sample", False):
        sample_dir = Path("tmp/visual_local_test/samples")
        sample_dir.mkdir(parents=True, exist_ok=True)
        sample_name = (args.product_name or case.get("product_name", "sample")).replace(" ", "_")[:30]
        sample_path = sample_dir / f"{sample_name}.png"
        generate_sample_image(sample_path, label=case.get("product_name", "SAMPLE")[:40])
        local_image_bytes = sample_path.read_bytes()
        local_image_path = sample_path
        _ok(f"Generated sample image: {sample_path} ({len(local_image_bytes) / 1024:.1f} KB)")

    image_url = args.image_url or case.get("image_url", "")
    if not image_url and not local_image_bytes:
        _err("No image source. Use --image-url, --local-image, --generate-sample, or --case.")
        return

    product_name = case["product_name"]
    brand_name = case.get("brand_name", "")
    brand_soul = case.get("brand_soul", "")
    hook_text = case.get("hook_text", "New Collection")
    description = case.get("description", "")

    # Determine steps to run
    all_steps = {"mask", "refine", "ad", "hero"}
    if args.steps:
        steps = {s.strip().lower() for s in args.steps.split(",")}
        invalid = steps - all_steps
        if invalid:
            _err(f"Unknown steps: {invalid}. Valid: {all_steps}")
            return
    else:
        steps = all_steps

    # FAL_KEY check
    fal_key = os.getenv("FAL_KEY", "")
    needs_fal = steps & {"refine", "ad", "hero"}
    if needs_fal and not fal_key:
        _err("FAL_KEY environment variable is required for fal.ai steps.")
        _info("Set it:  export FAL_KEY=your-key-here")
        _info("Or pass: FAL_KEY=your-key python scripts/local_visual_test.py ...")
        return

    # Create output directory
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("tmp/visual_local_test") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Print test case summary
    _banner("Visual Pipeline — Local Integration Test")
    _step(f"Product:      {product_name}")
    _step(f"Brand:        {brand_name or '(none)'}")
    _step(f"Hook text:    \"{hook_text}\"")
    if local_image_path:
        _step(f"Image src:    {local_image_path} (local file)")
    else:
        _step(f"Image URL:    {image_url}")
    _step(f"Steps:        {', '.join(sorted(steps))}")
    _step(f"Output dir:   {out_dir}")
    if description:
        _info(f"Description:  {description[:100]}...")
    if brand_soul:
        _info(f"Brand Soul:   {brand_soul[:100]}...")
    print()

    # Save test metadata
    import json
    meta = {
        "run_id": run_id,
        "product_name": product_name,
        "brand_name": brand_name,
        "brand_soul": brand_soul,
        "hook_text": hook_text,
        "image_url": image_url,
        "description": description,
        "steps": sorted(steps),
        "fal_key_set": bool(fal_key),
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    # Build prompts
    inpaint_prompt = build_inpaint_prompt(brand_soul=brand_soul)
    hero_prompt = build_hero_prompt(brand_soul=brand_soul)

    # Initialise service
    svc = VisualService(fal_key=fal_key)

    pipeline_t0 = time.time()
    results: Dict[str, Any] = {}

    # --- Step 1: Mask ---
    masked_bytes = None
    if "mask" in steps:
        masked_bytes = await step_mask(svc, image_url, out_dir, local_image_bytes=local_image_bytes)
        results["masked"] = masked_bytes is not None

        if masked_bytes is None and "refine" in steps:
            _warn("Skipping refine/ad/hero — masking failed")
            steps -= {"refine", "ad", "hero"}

    # --- Step 2: Refine ---
    refined_url = None
    if "refine" in steps:
        if masked_bytes is None:
            # If mask step was skipped, try using a pre-existing masked file
            prev_mask = out_dir / "01_masked_product.png"
            if prev_mask.exists():
                _info("Loading masked product from previous run...")
                masked_bytes = prev_mask.read_bytes()
            else:
                _warn("No masked image available — running masking first...")
                masked_bytes = await step_mask(svc, image_url, out_dir, local_image_bytes=local_image_bytes)

        if masked_bytes:
            refined_url = await step_refine(svc, masked_bytes, inpaint_prompt, out_dir)
            results["refined"] = refined_url is not None
        else:
            _warn("Skipping refine — no masked image")
            results["refined"] = False

    # --- Step 3: Ad ---
    if "ad" in steps:
        if refined_url:
            ad_url = await step_ad(svc, refined_url, hook_text, brand_name, out_dir)
            results["ad"] = ad_url is not None
        else:
            _warn("Skipping ad — no refined image URL")
            results["ad"] = False

    # --- Step 4: Hero ---
    if "hero" in steps:
        if refined_url:
            hero_url = await step_hero(svc, refined_url, hero_prompt, out_dir)
            results["hero"] = hero_url is not None
        else:
            _warn("Skipping hero — no refined image URL")
            results["hero"] = False

    # --- Summary ---
    total_elapsed = time.time() - pipeline_t0
    _banner("Results Summary")

    for step_name, success in results.items():
        icon = f"{_C.GREEN}✔{_C.RESET}" if success else f"{_C.RED}✘{_C.RESET}"
        print(f"    {icon}  {step_name}")

    print()
    _step(f"Total time:  {total_elapsed:.1f}s")
    _step(f"Output dir:  {out_dir.resolve()}")
    _info(f"Open folder: open {out_dir.resolve()}")

    # Save results
    results_meta = {
        "run_id": run_id,
        "elapsed_s": round(total_elapsed, 1),
        "results": results,
    }
    (out_dir / "results.json").write_text(json.dumps(results_meta, indent=2))

    # Count successes
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    if passed == total:
        _ok(f"All {total} steps passed!")
    else:
        _warn(f"{passed}/{total} steps passed")


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local Visual Pipeline Test — real fal.ai calls, local storage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Full pipeline with built-in "ceramic bowl" test case
  FAL_KEY=xxx python scripts/local_visual_test.py --case ceramic-bowl

  # Only background removal (no fal.ai key needed)
  python scripts/local_visual_test.py --case ceramic-bowl --steps mask

  # Use your own local product image (no URL needed)
  FAL_KEY=xxx python scripts/local_visual_test.py \\
      --local-image ~/photos/my-product.jpg \\
      --product-name "My Widget" --hook-text "Shop Now"

  # Generate a sample image and test the pipeline (no external deps)
  FAL_KEY=xxx python scripts/local_visual_test.py --generate-sample --case ceramic-bowl

  # Just masking with a generated sample (no fal.ai key needed!)
  python scripts/local_visual_test.py --generate-sample --case ceramic-bowl --steps mask

  # Custom Shopify product image URL
  FAL_KEY=xxx python scripts/local_visual_test.py \\
      --image-url "https://cdn.shopify.com/s/files/.../product.jpg" \\
      --product-name "My Widget" \\
      --hook-text "Shop Now" \\
      --brand-soul "Modern minimalist design"

  # List all built-in test cases
  python scripts/local_visual_test.py --list-cases
""",
    )

    # Test case selection
    case_group = parser.add_argument_group("Test Case")
    case_group.add_argument(
        "--case", "-c",
        choices=list(TEST_CASES.keys()),
        help="Built-in test case to run.",
    )
    case_group.add_argument(
        "--list-cases", action="store_true",
        help="List all built-in test cases and exit.",
    )

    # Custom product data
    custom_group = parser.add_argument_group("Custom Product (overrides --case)")
    custom_group.add_argument("--image-url", help="Product image URL (HTTPS, Shopify CDN or any public URL)")
    custom_group.add_argument("--local-image", "-l", help="Path to a local product image (skips URL download)")
    custom_group.add_argument("--generate-sample", "-g", action="store_true",
                              help="Generate a sample product image with Pillow (no external image needed)")
    custom_group.add_argument("--product-name", help="Product name")
    custom_group.add_argument("--brand-name", help="Brand name")
    custom_group.add_argument("--brand-soul", help="Brand Soul description for prompt engineering")
    custom_group.add_argument("--hook-text", help="Marketing hook text for ad typography")
    custom_group.add_argument("--description", help="Product description")

    # Pipeline control
    pipeline_group = parser.add_argument_group("Pipeline")
    pipeline_group.add_argument(
        "--steps", "-s",
        help="Comma-separated steps to run: mask,refine,ad,hero (default: all)",
    )

    args = parser.parse_args()

    # Handle --list-cases
    if args.list_cases:
        print(f"\n{_C.BOLD}Built-in Test Cases:{_C.RESET}\n")
        for name, case in TEST_CASES.items():
            print(f"  {_C.CYAN}{name:<16}{_C.RESET}  {case['product_name']}")
            print(f"  {'':16}  Brand: {case.get('brand_name', 'N/A')}")
            print(f"  {'':16}  Hook:  \"{case.get('hook_text', '')}\"")
            print(f"  {'':16}  Image: {case.get('image_url', 'N/A')[:70]}...")
            print()
        print(f"  Usage: FAL_KEY=xxx python scripts/local_visual_test.py --case {list(TEST_CASES.keys())[0]}")
        return

    # Need either --case, --image-url, --local-image, or --generate-sample
    if not args.case and not args.image_url and not args.local_image and not args.generate_sample:
        parser.error("Provide --case, --image-url, --local-image, or --generate-sample. Use --list-cases to see options.")

    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()

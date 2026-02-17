"""
Prompt templates for the VisualAgent pipeline.

These prompts are injected with Brand Soul context and product metadata
to drive the fal.ai image generation models.
"""

# ---------------------------------------------------------------------------
# Background refinement (Flux 2.0 Pro inpainting)
# ---------------------------------------------------------------------------

INPAINT_BACKGROUND_PROMPT_TEMPLATE = """\
Professional product photography background.
{brand_style}
Clean, well-lit studio environment that complements the product.
Subtle, non-distracting background with consistent global lighting.
Remove all text, logos, watermarks, Japanese characters, and typographic overlays from the image.
The final image must contain only the product on a clean background -- no text of any kind.
High-end e-commerce aesthetic. Premium quality.
{extra_context}
"""

# ---------------------------------------------------------------------------
# Marketing Ad (Ideogram 3.0 with typography)
# ---------------------------------------------------------------------------

AD_COMPOSITION_PROMPT_TEMPLATE = """\
Professional social media marketing advertisement for {product_name}.
{brand_style}
Render the text "{hook_text}" in bold, elegant typography that is clearly \
legible and well-positioned on the image.
Spell every word correctly -- double-check spelling before rendering.
Do NOT misspell, abbreviate, or alter the provided text in any way.
Render the text exactly as provided, character for character.
{brand_name_line}
Modern, eye-catching design. High contrast for mobile viewing.
Instagram-ready square format. Print-ready quality. No watermarks.
"""

# ---------------------------------------------------------------------------
# Hero Banner Outpainting (SD 3.5)
# ---------------------------------------------------------------------------

HERO_BANNER_PROMPT_TEMPLATE = """\
Expand this product photograph into a wide 16:9 hero banner.
Keep the product centered and prominent.
{brand_style}
Extend the background seamlessly with consistent lighting, color palette, \
and visual style. Suitable for a Shopify collection page header or blog hero image.
Professional e-commerce photography. Ultra high quality.
{extra_context}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_inpaint_prompt(
    brand_soul: str = "",
    extra_context: str = "",
) -> str:
    """Build the background refinement prompt from Brand Soul context."""
    brand_style = ""
    if brand_soul:
        brand_style = (
            f"Brand aesthetic: {brand_soul[:500]}. "
            f"The background should reflect this brand identity."
        )
    return INPAINT_BACKGROUND_PROMPT_TEMPLATE.format(
        brand_style=brand_style,
        extra_context=extra_context,
    ).strip()


def build_ad_prompt(
    product_name: str,
    hook_text: str,
    brand_name: str = "",
    brand_soul: str = "",
) -> str:
    """Build the Ideogram ad generation prompt."""
    brand_style = ""
    if brand_soul:
        brand_style = f"Brand aesthetic: {brand_soul[:300]}."

    brand_name_line = ""
    if brand_name:
        brand_name_line = (
            f'Include the brand name "{brand_name}" in a smaller, '
            f"elegant font in the corner."
        )

    return AD_COMPOSITION_PROMPT_TEMPLATE.format(
        product_name=product_name,
        brand_style=brand_style,
        hook_text=hook_text,
        brand_name_line=brand_name_line,
    ).strip()


def build_hero_prompt(
    brand_soul: str = "",
    extra_context: str = "",
) -> str:
    """Build the hero banner outpainting prompt."""
    brand_style = ""
    if brand_soul:
        brand_style = (
            f"Brand aesthetic: {brand_soul[:500]}. "
            f"Maintain visual consistency with the brand identity."
        )
    return HERO_BANNER_PROMPT_TEMPLATE.format(
        brand_style=brand_style,
        extra_context=extra_context,
    ).strip()

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
Do NOT add hashtags, social media captions, or any extra text beyond what is specified.
{brand_name_line}
Modern, eye-catching design. High contrast for mobile viewing.
Instagram-ready square format. Print-ready quality. No watermarks. No hashtags.
"""

# ---------------------------------------------------------------------------
# Hero Banner Outpainting (fal.ai outpaint-v2, 500-char prompt limit)
# ---------------------------------------------------------------------------

HERO_BANNER_PROMPT_TEMPLATE = """\
Expand product photo into wide 16:9 hero banner. Product centered and prominent.
{brand_style}\
Extend background seamlessly with consistent lighting and color palette.
No text, words, letters, logos, or writing of any kind. Purely visual.
Professional e-commerce photography. Ultra high quality.\
{extra_context}
"""

# fal.ai outpaint-v2 enforces a hard 500-character prompt limit
_HERO_PROMPT_HARD_CAP = 500


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


def _distill_brand_aesthetic(brand_soul: str, max_len: int = 120) -> str:
    """Extract a short visual-friendly aesthetic hint from brand soul.

    The brand_soul may be a ``str()``-ified dict (from strategic_intelligence)
    or plain descriptive text.  Either way we return a concise phrase suitable
    for an image-generation prompt (archetype + a handful of power words).
    """
    import ast
    import re

    if not brand_soul:
        return ""

    # Strategic intelligence dict stringified via str()
    try:
        data = ast.literal_eval(brand_soul)
        if isinstance(data, dict):
            parts: list[str] = []
            archetype = data.get("archetype", "")
            if archetype:
                parts.append(archetype.replace("_", " ").title())
            words = data.get("power_words", [])
            if words:
                parts.append(", ".join(words[:5]))
            return ". ".join(parts)[:max_len]
    except (ValueError, SyntaxError):
        pass

    # Plain text fallback — first meaningful fragment
    clean = re.sub(r"\s+", " ", brand_soul).strip()
    return clean[:max_len]


def build_hero_prompt(
    brand_soul: str = "",
    extra_context: str = "",
) -> str:
    """Build the hero banner outpainting prompt (max 500 chars for fal.ai)."""
    brand_style = ""
    if brand_soul:
        aesthetic = _distill_brand_aesthetic(brand_soul, max_len=120)
        if aesthetic:
            brand_style = f"Brand aesthetic: {aesthetic}.\n"

    prompt = HERO_BANNER_PROMPT_TEMPLATE.format(
        brand_style=brand_style,
        extra_context=extra_context,
    ).strip()

    if len(prompt) > _HERO_PROMPT_HARD_CAP:
        prompt = prompt[: _HERO_PROMPT_HARD_CAP - 3] + "..."
    return prompt

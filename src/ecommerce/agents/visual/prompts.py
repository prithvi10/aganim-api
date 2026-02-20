"""
Prompt templates for the VisualAgent pipeline.

These prompts are injected with Brand Soul context and product metadata
to drive the fal.ai image generation models.
"""

from __future__ import annotations

from typing import List, Optional

# ---------------------------------------------------------------------------
# Ad Style Definitions (used by Marketing Studio)
# ---------------------------------------------------------------------------

AD_STYLE_PROMPTS: dict[str, str] = {
    "aesthetic": "Soft pastel tones, minimalist layout, clean negative space, subtle shadows, elegant simplicity",
    "trendy": "Bold vibrant colors, geometric patterns, modern pop art style, dynamic angles, eye-catching contrast",
    "nature": "Natural earth tones, botanical leaves and greenery, wooden or stone surface, organic textures, warm sunlight",
    "ingredients": "Related ingredients artfully arranged around the product, e.g. coffee beans near coffee, oranges near juice, herbs near tea",
    "luxury": "Dark moody background, dramatic spotlight from above, metallic and gold accents, premium feel, rich textures",
    "studio": "Clean white or light grey studio background, professional product photography lighting, soft diffused shadows",
    "seasonal": "Festive seasonal decorations matching current holiday, warm celebratory atmosphere, themed props and colors",
    "lifestyle": "Product placed naturally in a real-world setting, cozy home interior, modern cafe, or stylish workspace",
    "flat_lay": "Top-down flat lay arrangement with complementary props, styled on a textured surface, organized composition",
    "gradient": "Modern smooth gradient background with soft color transition, product centered with clean negative space",
}

AD_STYLE_LABELS: dict[str, str] = {
    "aesthetic": "Aesthetic",
    "trendy": "Trendy",
    "nature": "Nature",
    "ingredients": "Ingredients",
    "luxury": "Luxury",
    "studio": "Studio",
    "seasonal": "Seasonal",
    "lifestyle": "Lifestyle",
    "flat_lay": "Flat Lay",
    "gradient": "Gradient",
}

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
            result = ". ".join(parts)[:max_len]
            return result if result else ""
    except (ValueError, SyntaxError):
        pass

    # If it looks like a stringified dict/list that we failed to parse
    # (e.g. truncated), discard it to avoid leaking raw code into prompts.
    stripped = brand_soul.strip()
    if stripped.startswith(("{", "[", "OrderedDict")):
        return ""

    # Plain text fallback — first meaningful fragment
    clean = re.sub(r"\s+", " ", stripped)
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


# ---------------------------------------------------------------------------
# Prop inference (deterministic, keyword-based)
# ---------------------------------------------------------------------------

_PROP_KEYWORDS = {
    "beverage": [
        (["coffee", "espresso", "latte", "mocha"], "roasted coffee beans, cinnamon sticks"),
        (["tea", "matcha", "chai", "green tea"], "dried tea leaves, matcha powder"),
        (["juice", "orange", "lemon", "citrus"], "fresh citrus slices, mint leaves"),
        (["sake", "rice wine"], "cedar masu box, cherry blossom petals"),
        (["wine", "cabernet", "merlot"], "wine cork, dark grapes"),
        (["beer", "ale", "lager", "ipa"], "hops, wheat stalks"),
        (["smoothie", "berry"], "fresh berries, sliced banana"),
        (["water", "sparkling"], "ice cubes, lime wedge"),
        (["soda", "cola"], "ice cubes, condensation droplets"),
    ],
    "food": [
        (["chocolate", "cocoa"], "cocoa beans, dark chocolate shavings"),
        (["honey"], "honeycomb, wooden dipper"),
        (["jam", "preserve", "marmalade"], "fresh fruit, rustic bread slices"),
        (["olive oil", "olive"], "green olives, rosemary sprig"),
        (["spice", "curry", "masala"], "whole spices, cardamom pods, star anise"),
        (["snack", "chips", "cracker"], "scattered crumbs, herbs"),
        (["pasta", "noodle"], "dried herbs, garlic cloves, parmesan"),
        (["sauce", "ketchup", "mustard"], "fresh tomatoes, herb sprigs"),
    ],
    "skincare": [
        (["vitamin c", "citrus", "brightening"], "orange slices, golden serum drops"),
        (["retinol", "anti-aging"], "smooth pebbles, gold flakes"),
        (["aloe", "soothing"], "aloe vera leaves, water droplets"),
        (["hyaluronic", "hydrating", "moistur"], "water splash, dewy petals"),
        (["charcoal", "detox"], "activated charcoal chunks, eucalyptus"),
        (["rose", "floral"], "dried rose petals, rose buds"),
        (["lavender"], "lavender sprigs, purple fabric"),
        (["sunscreen", "spf", "sun"], "sand grains, tropical leaf"),
    ],
    "fragrance": [
        (["wood", "cedar", "sandalwood", "oud"], "cedar shavings, bark pieces"),
        (["floral", "jasmine", "rose", "lily"], "scattered flower petals"),
        (["citrus", "bergamot", "neroli"], "citrus zest, orange peel curls"),
        (["vanilla", "amber"], "vanilla pods, warm amber stones"),
        (["musk", "leather"], "leather swatch, dark fabric"),
    ],
    "general": [
        (["organic", "natural", "eco"], "green leaves, raw cotton"),
        (["premium", "luxury", "gold"], "gold leaf accents, silk fabric"),
        (["handmade", "artisan", "craft"], "raw materials, textured linen"),
        (["japanese", "japan", "zen"], "bamboo mat, zen stones"),
        (["minimalist", "modern", "clean"], "geometric shapes, clean surfaces"),
    ],
}

_STYLE_SURFACES = {
    "aesthetic": "polished marble surface",
    "trendy": "terrazzo surface with geometric tiles",
    "nature": "weathered oak wood surface with moss accents",
    "ingredients": "dark slate surface",
    "luxury": "black marble surface with gold veining",
    "studio": "clean light grey seamless backdrop",
    "seasonal": "festive surface with seasonal decorations",
    "lifestyle": "styled table in a modern living space",
    "flat_lay": "textured linen surface shot from above",
    "gradient": "smooth gradient backdrop",
}


def infer_props(
    product_name: str = "",
    product_type: str = "",
    tags: Optional[List[str]] = None,
) -> str:
    """Infer decorative props from product signals (name, type, tags).

    Returns a short comma-separated phrase suitable for an image prompt,
    or an empty string if nothing matches.
    """
    signals = " ".join([
        product_name.lower(),
        product_type.lower(),
        " ".join(t.lower() for t in (tags or [])),
    ])

    for _category, rules in _PROP_KEYWORDS.items():
        for keywords, prop_phrase in rules:
            if any(kw in signals for kw in keywords):
                return prop_phrase

    return ""


# ---------------------------------------------------------------------------
# Style-aware background prompt (Marketing Studio -- Flux Fill) [LEGACY]
# ---------------------------------------------------------------------------

STYLED_BACKGROUND_PROMPT_TEMPLATE = """\
Professional marketing product photography.
The product is placed on a {surface}.
{style_description}
{props_line}\
{brand_style}
High-end e-commerce quality, 8k resolution.
The lighting is consistent, casting realistic soft shadows from the product onto the generated environment.
No text, words, letters, logos, or writing of any kind. Purely visual.
"""


def build_styled_background_prompt(
    ad_style: str,
    brand_soul: str = "",
    product_name: str = "",
    product_type: str = "",
    tags: Optional[List[str]] = None,
) -> str:
    """Build a purely visual Flux Fill prompt for masked inpainting.

    Text overlay is handled separately by PIL; this prompt must NOT request
    any text rendering from the model.
    """
    style_description = AD_STYLE_PROMPTS.get(ad_style, AD_STYLE_PROMPTS["aesthetic"])
    surface = _STYLE_SURFACES.get(ad_style, "clean surface")

    brand_style = ""
    if brand_soul:
        aesthetic = _distill_brand_aesthetic(brand_soul, max_len=200)
        if aesthetic:
            brand_style = f"{aesthetic} aesthetic. "

    props = infer_props(product_name, product_type, tags)
    props_line = f"Accompanied by {props}. " if props else ""

    return STYLED_BACKGROUND_PROMPT_TEMPLATE.format(
        surface=surface,
        style_description=style_description,
        props_line=props_line,
        brand_style=brand_style,
    ).strip()


# ---------------------------------------------------------------------------
# Nano Banana marketing prompt (fal-ai/nano-banana/edit)
# ---------------------------------------------------------------------------

NANO_BANANA_MARKETING_TEMPLATE = """\
Professional marketing product photo for Instagram.
Place the exact product from the reference image in a beautiful, well-lit setting with complementary styling and props.
Preserve the product faithfully -- same shape, colors, labels, and packaging.
{brand_style}High-quality e-commerce photography. Eye-catching composition.
No text, words, letters, logos, or watermarks.
"""


def build_nano_banana_prompt(
    product_name: str = "",
    brand_soul: str = "",
) -> str:
    """Build a fidelity-first prompt for Nano Banana /edit.

    The prompt prioritises faithful reproduction of the reference product.
    ``brand_soul`` is supported but the caller should only pass a non-empty
    value when brand styling is explicitly enabled (``use_brand_style=True``
    on ProductAdGenerator); by default it is empty so the model focuses
    entirely on the reference image.
    """
    brand_style = ""
    if brand_soul:
        aesthetic = _distill_brand_aesthetic(brand_soul, max_len=120)
        if aesthetic:
            brand_style = f"{aesthetic} aesthetic. "

    product_name_line = ""
    if product_name:
        product_name_line = f"Product: {product_name}. "

    prompt = NANO_BANANA_MARKETING_TEMPLATE.format(
        brand_style=brand_style,
    ).strip()

    if product_name_line:
        prompt = product_name_line + prompt

    return prompt


# ---------------------------------------------------------------------------
# Hero banner prompts (fal-ai/nano-banana text-to-image)
# ---------------------------------------------------------------------------

COLLECTION_HERO_TEMPLATE = """\
Wide cinematic hero banner for an e-commerce product collection called "{collection_name}".
{description_line}\
{products_line}\
{brand_style}\
Professional product photography composition with beautiful lighting and styling.
High-end e-commerce visual, 8k resolution.
No text, words, letters, logos, or watermarks. Purely visual.
"""

BLOG_HERO_TEMPLATE = """\
Wide cinematic hero banner for a blog article about "{subject}" in the {category} category.
{context_line}\
{brand_style}\
Editorial photography style with atmospheric mood and beautiful lighting.
High-end visual, 8k resolution.
No text, words, letters, logos, or watermarks. Purely visual.
"""

HERO_SECTION_TEMPLATE = """\
Wide cinematic hero banner with a "{subject}" theme.
{overlay_line}\
{brand_style}\
Atmospheric, high-end visual with dramatic lighting and rich composition.
Suitable for a landing page hero section. 8k resolution.
No text, words, letters, logos, or watermarks. Purely visual.
"""


def build_collection_hero_prompt(
    collection_name: str,
    description: str = "",
    product_names: Optional[List[str]] = None,
    brand_soul: str = "",
) -> str:
    """Build a hero banner prompt for a product collection."""
    brand_style = ""
    if brand_soul:
        aesthetic = _distill_brand_aesthetic(brand_soul, max_len=120)
        if aesthetic:
            brand_style = f"{aesthetic} aesthetic. "

    description_line = f"{description}. " if description else ""
    products_line = ""
    if product_names:
        names = ", ".join(product_names[:8])
        products_line = f"Featuring products: {names}. "

    return COLLECTION_HERO_TEMPLATE.format(
        collection_name=collection_name,
        description_line=description_line,
        products_line=products_line,
        brand_style=brand_style,
    ).strip()


def build_blog_hero_prompt(
    subject: str,
    category: str = "General",
    context: str = "",
    brand_soul: str = "",
) -> str:
    """Build a hero banner prompt for a blog post."""
    brand_style = ""
    if brand_soul:
        aesthetic = _distill_brand_aesthetic(brand_soul, max_len=120)
        if aesthetic:
            brand_style = f"{aesthetic} aesthetic. "

    context_line = f"{context}. " if context else ""

    return BLOG_HERO_TEMPLATE.format(
        subject=subject,
        category=category,
        context_line=context_line,
        brand_style=brand_style,
    ).strip()


def build_hero_section_prompt(
    subject: str,
    overlay_text: str = "",
    brand_soul: str = "",
) -> str:
    """Build a hero banner prompt for a landing page hero section."""
    brand_style = ""
    if brand_soul:
        aesthetic = _distill_brand_aesthetic(brand_soul, max_len=120)
        if aesthetic:
            brand_style = f"{aesthetic} aesthetic. "

    overlay_line = f"Visual theme inspired by: {overlay_text}. " if overlay_text else ""

    return HERO_SECTION_TEMPLATE.format(
        subject=subject,
        overlay_line=overlay_line,
        brand_style=brand_style,
    ).strip()

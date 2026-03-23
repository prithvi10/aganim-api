"""
Prompt templates for the VisualAgent pipeline.

These prompts are injected with Brand Soul context and product metadata
to drive the fal.ai image generation models.

Includes:
- Legacy ad/inpaint/hero templates (used by existing pipelines)
- Art-Directed style templates (Informative, Minimalist, Attractive, Seasonal)
  driven by VisualBrief from the Art Director LLM service
"""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.ecommerce.services.art_director import VisualBrief

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
Photorealistic, shallow depth of field. Blurred background texture, NOT a detailed scene.
No text, words, letters, logos, or writing of any kind. Purely visual.
Professional e-commerce photography. Ultra high quality.\
NOT illustrated, cartoon, or digitally painted.\
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
# Nano Banana refinement prompt (fal-ai/nano-banana/edit -- fidelity-first)
# ---------------------------------------------------------------------------

NANO_BANANA_REFINEMENT_TEMPLATE = """\
Professional e-commerce product photo. Clean studio background.
CRITICAL FIDELITY RULES -- follow these exactly:
- Reproduce the product from the reference image with 100% fidelity.
- Keep the EXACT same shape, size, proportions, color, texture, material, \
and every physical detail of the product.
- Preserve ALL labels, brand names, logos, and text that are physically \
printed, embossed, or attached to the product or its packaging.
- Do NOT alter, redraw, or reinterpret any part of the physical product.
CLEANUP RULES:
- Remove all overlay text, promotional banners, sale stickers, price tags, \
watermarks, and decorative graphics that are NOT part of the physical product.
- Replace the background with a clean, well-lit studio surface (white or \
light grey).
{brand_style}Soft, even lighting. No harsh shadows. No added text or graphics.
"""


def build_nano_banana_refinement_prompt(brand_soul: str = "") -> str:
    """Build a fidelity-first prompt for Nano Banana /edit image refinement.

    Unlike the marketing prompt, this prompt instructs the model to reproduce
    the product exactly while only cleaning up the background and removing
    non-product overlay text.
    """
    brand_style = ""
    if brand_soul:
        aesthetic = _distill_brand_aesthetic(brand_soul, max_len=120)
        if aesthetic:
            brand_style = f"{aesthetic} aesthetic. "

    return NANO_BANANA_REFINEMENT_TEMPLATE.format(
        brand_style=brand_style,
    ).strip()


# ---------------------------------------------------------------------------
# Hero banner prompts (fal-ai/nano-banana text-to-image)
# ---------------------------------------------------------------------------

COLLECTION_HERO_TEMPLATE = """\
Professional e-commerce photography hero banner for a collection called "{collection_name}".
Photorealistic, high-end, cinematic. Shallow depth of field.
{products_line}Products artfully arranged on a premium surface that complements the collection theme.
{description_line}\
{brand_style}\
Background: subtly blurred photorealistic backdrop -- a texture or gentle environment, NOT a sharp detailed scene.
Lighting: soft, diffused studio lighting creating gentle shadows.
8k resolution. No text, words, letters, logos, or watermarks. Purely visual.
NOT illustrated, cartoon, or digitally painted.
"""

BLOG_HERO_TEMPLATE = """\
Photorealistic editorial hero banner for a blog article about "{subject}" in the {category} category.
High-end commercial photography. Shallow depth of field with soft bokeh.
{context_line}\
{brand_style}\
Background: subtly blurred photographic backdrop with muted tones -- NOT an illustrated scene.
Lighting: soft diffused natural light with gentle shadows.
8k resolution. No text, words, letters, logos, or watermarks. Purely visual.
NOT illustrated, cartoon, or digitally painted.
"""

HERO_SECTION_TEMPLATE = """\
Photorealistic hero banner with a "{subject}" theme.
High-end commercial photography. Shallow depth of field.
{description_line}\
{brand_style}\
Background: soft, out-of-focus photographic backdrop that frames the subject -- NOT a busy landscape.
Lighting: beautiful natural light, organic and high-quality.
8k resolution. No text, words, letters, logos, or watermarks. Purely visual.
NOT illustrated, cartoon, or digitally painted.
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
    short_description: str = "",
    brand_soul: str = "",
) -> str:
    """Build a hero banner prompt for a landing page hero section."""
    brand_style = ""
    if brand_soul:
        aesthetic = _distill_brand_aesthetic(brand_soul, max_len=120)
        if aesthetic:
            brand_style = f"{aesthetic} aesthetic. "

    description_line = f"{short_description}. " if short_description else ""

    return HERO_SECTION_TEMPLATE.format(
        subject=subject,
        description_line=description_line,
        brand_style=brand_style,
    ).strip()


# ---------------------------------------------------------------------------
# Art-Directed Style Templates (driven by VisualBrief from Art Director LLM)
# ---------------------------------------------------------------------------

INFORMATIVE_STYLE_TEMPLATE = """\
Professional e-commerce hero banner. Photorealistic, cinematic, shallow depth of field.
Product: {product_name} placed on {surface_material}.
Background: Subtly blurred {environment}. NOT a sharp detailed scene.
Lighting: {lighting_scheme}.
Color palette: {color_palette}.
Render the text "{product_name}" in small, elegant typography that matches the color palette.
{logo_line}\
Spell every word exactly as provided. Do NOT add extra text, hashtags, or captions.
8k resolution. Photorealistic only -- NOT illustrated, cartoon, or digitally painted.
"""

MINIMALIST_STYLE_TEMPLATE = """\
Clean product photography on a minimal {surface_material} surface.
Single product isolated with ample negative space.
Lighting: {lighting_scheme}. Soft, even illumination.
Background: Solid or subtly gradient, matching {color_palette}.
No props, no clutter, no text, no logos. Pure product focus.
8k resolution. Photorealistic studio photography.
NOT illustrated, cartoon, or digitally painted.
"""

ATTRACTIVE_STYLE_TEMPLATE = """\
Professional e-commerce photography. Photorealistic, high-end, cinematic. Shallow depth of field.
Product placed on {surface_material}, accompanied by {suggested_props}.
Background: Subtly blurred {environment}. A texture or gentle atmosphere, NOT a busy landscape.
Lighting: {lighting_scheme}.
Color palette: {color_palette}.
No text, words, letters, logos, or watermarks. Purely visual.
8k resolution. NOT illustrated, cartoon, or digitally painted.
"""

SEASONAL_STYLE_TEMPLATE = """\
Professional e-commerce photography for {season} season. Photorealistic, cinematic, warm.
Product placed on {surface_material}, surrounded by seasonal elements ({season_props}).
Background: Subtly blurred {environment} with {season} atmosphere.
Lighting: {lighting_scheme}.
Color palette: {color_palette}.
No text, words, letters, logos, or watermarks. Purely visual.
8k resolution. NOT illustrated, cartoon, or digitally painted.
"""

MONOCHROME_STYLE_TEMPLATE = """\
Black and white fine-art photography. High contrast, dramatic, editorial.
Subject: {hero_subject} on {surface_material}.
Background: {environment}, rendered in grayscale with rich tonal range.
Lighting: {lighting_scheme}. Deep blacks, bright highlights, no mid-tone muddiness.
No color. Monochrome only. No text, logos, or watermarks.
8k resolution. Photorealistic. NOT illustrated, cartoon, or digitally painted.
"""

_STYLE_TEMPLATES = {
    "informative": INFORMATIVE_STYLE_TEMPLATE,
    "minimalist": MINIMALIST_STYLE_TEMPLATE,
    "attractive": ATTRACTIVE_STYLE_TEMPLATE,
    "seasonal": SEASONAL_STYLE_TEMPLATE,
    "monochrome": MONOCHROME_STYLE_TEMPLATE,
}

_IMG2IMG_FIDELITY_PREAMBLE = """\
CRITICAL: Use the EXACT product from the reference image. \
Preserve it faithfully -- same shape, colors, labels, packaging, and branding. \
Do NOT invent, reimagine, or alter the product in any way. \
Place the real product from the reference into the scene described below.
"""


def build_styled_prompt(
    style: str,
    brief: "VisualBrief",
    product_name: str = "",
    brand_name: str = "",
    season: str = "",
    season_props: str = "",
    is_img2img: bool = False,
) -> str:
    """Build an image-generation prompt from a VisualBrief and style.

    Parameters
    ----------
    style : str
        One of "informative", "minimalist", "attractive", "seasonal".
    brief : VisualBrief
        Structured art-direction output from the Art Director LLM.
    product_name : str
        Display name of the product (used in Informative template text).
    brand_name : str
        Shop/brand name (used for logo rendering in Informative style).
    season : str
        Current season name (for Seasonal style).
    season_props : str
        Seasonal prop descriptions (for Seasonal style).
    is_img2img : bool
        When True, prepends strong product-fidelity instructions so the
        model preserves the exact product from the reference image.
    """
    template = _STYLE_TEMPLATES.get(style, ATTRACTIVE_STYLE_TEMPLATE)
    palette_str = ", ".join(brief.color_palette[:3])

    logo_line = ""
    if style == "informative" and brand_name:
        logo_line = (
            f'Include the brand logo "{brand_name}" subtly in the corner, '
            f"matching the scene colors.\n"
        )

    fmt = dict(
        product_name=product_name,
        hero_subject=product_name,
        surface_material=brief.surface_material,
        environment=brief.environment,
        lighting_scheme=brief.lighting_scheme,
        color_palette=palette_str,
        suggested_props=brief.suggested_props,
        logo_line=logo_line,
        season=season or "spring",
        season_props=season_props or brief.suggested_props,
    )

    try:
        prompt = template.format(**fmt).strip()
    except KeyError:
        prompt = template.format_map(_SafeFormatDict(**fmt)).strip()

    if is_img2img:
        prompt = _IMG2IMG_FIDELITY_PREAMBLE + prompt

    return prompt


# ---------------------------------------------------------------------------
# Blog-specific hero prompt builder (uses visual_brief from blog LLM)
# ---------------------------------------------------------------------------

_BLOG_HERO_BASE = """\
Photorealistic editorial hero image for a blog article.
Subject: {hero_subject}.
Surface: {surface}.
Background: Subtly blurred {environment}. NOT a sharp detailed scene.
Lighting: {lighting}.
STRICT: No actors, no faces, no human beings. Still life or process shot only.
8k resolution. NOT illustrated, cartoon, or digitally painted.
"""

_BLOG_HERO_MONOCHROME = """\
Black and white fine-art editorial photograph for a blog article.
Subject: {hero_subject}.
Surface: {surface}.
Background: {environment}, rendered in grayscale with rich tonal range.
Lighting: {lighting}. Deep blacks, bright highlights, no mid-tone muddiness.
STRICT: No actors, no faces, no human beings. Still life or process shot only.
No color. Monochrome only. No text, logos, or watermarks.
8k resolution. Photorealistic. NOT illustrated, cartoon, or digitally painted.
"""


def build_blog_hero_from_brief(
    visual_brief: dict,
    image_style: str = "attractive",
    is_img2img: bool = False,
) -> str:
    """Build a hero image prompt from the blog LLM's visual_brief output.

    Parameters
    ----------
    visual_brief : dict
        Must contain keys: hero_subject, surface, environment, lighting.
    image_style : str
        The user-selected style.  ``"monochrome"`` triggers B&W treatment;
        all other values use the standard editorial template.
    is_img2img : bool
        When True, prepends product-fidelity instructions.
    """
    brief_vars = {
        "hero_subject": visual_brief.get("hero_subject", "product arrangement"),
        "surface": visual_brief.get("surface", "clean surface"),
        "environment": visual_brief.get("environment", "soft neutral backdrop"),
        "lighting": visual_brief.get("lighting", "diffused natural light"),
    }

    template = _BLOG_HERO_MONOCHROME if image_style == "monochrome" else _BLOG_HERO_BASE
    prompt = template.format(**brief_vars).strip()

    if is_img2img:
        prompt = _IMG2IMG_FIDELITY_PREAMBLE + prompt

    return prompt


class _SafeFormatDict(dict):
    """Dict subclass that returns the key name for missing format keys."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"

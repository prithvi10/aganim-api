"""
Art Director Service -- LLM-powered visual brief generation.

Uses a structured LLM call (gpt-4o-mini) to analyze product metadata and
produce a VisualBrief JSON that drives style-specific image generation prompts.

The brief captures *physical* properties (surface textures, light angles,
color palettes) rather than marketing abstractions, giving the image model
concrete visual instructions.

LLM Cost: ~200 input + ~100 output tokens per call (~$0.00005 with gpt-4o-mini).
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, List

from pydantic import BaseModel, Field

from src.shared.logging.logger import get_logger

if TYPE_CHECKING:
    from src.agentic_core.llm.llm_service import LLMService

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Image style enum
# ---------------------------------------------------------------------------

class ImageStyle(str, Enum):
    INFORMATIVE = "informative"
    MINIMALIST = "minimalist"
    ATTRACTIVE = "attractive"
    SEASONAL = "seasonal"
    MONOCHROME = "monochrome"


# ---------------------------------------------------------------------------
# Visual Brief schema (returned by the Art Director LLM call)
# ---------------------------------------------------------------------------

class VisualBrief(BaseModel):
    """Structured art-direction output for image generation."""

    surface_material: str = Field(
        description="Physical surface the product sits on, e.g. 'weathered oak', 'honed marble', 'brushed linen'",
    )
    environment: str = Field(
        description="Blurred background atmosphere, e.g. 'misty morning tea garden', 'sun-drenched minimalist kitchen'",
    )
    lighting_scheme: str = Field(
        description="Light source and shadow quality, e.g. 'warm side-lighting with long soft shadows'",
    )
    color_palette: List[str] = Field(
        description="3 complementary color names or hex codes that match the product packaging",
    )
    suggested_props: str = Field(
        description="Contextual props for the product, e.g. 'roasted coffee beans, cinnamon sticks'",
    )


# ---------------------------------------------------------------------------
# Season detection
# ---------------------------------------------------------------------------

_NORTHERN_SEASONS = {
    (3, 5): "spring",
    (6, 8): "summer",
    (9, 11): "autumn",
    (12, 12): "winter",
    (1, 2): "winter",
}

_SEASON_PROPS = {
    "spring": "cherry blossom petals, fresh green leaves, pastel wildflowers",
    "summer": "sunflowers, citrus slices, seashells, warm sand",
    "autumn": "amber maple leaves, pinecones, dried wheat stalks",
    "winter": "frosted pine branches, cinnamon sticks, warm knit textures",
}


def get_current_season() -> str:
    """Return the current Northern-hemisphere season name."""
    month = date.today().month
    for (start, end), season in _NORTHERN_SEASONS.items():
        if start <= month <= end:
            return season
    return "spring"


def get_season_props(season: str) -> str:
    """Return default seasonal props for a given season."""
    return _SEASON_PROPS.get(season, _SEASON_PROPS["spring"])


# ---------------------------------------------------------------------------
# Art Director meta-prompt
# ---------------------------------------------------------------------------

_ART_DIRECTOR_SYSTEM = """\
You are a Senior Art Director at a high-end e-commerce photography studio. \
You think exclusively in terms of physical properties: surfaces, textures, \
light angles, color relationships, and spatial composition. \
You never use vague marketing language like "beautiful" or "eye-catching". \
Every direction must be concrete enough for a photographer to execute."""

_ART_DIRECTOR_USER = """\
Analyze the following product and create a visual brief for a {style} product photograph.

Product Name: {product_name}
Category: {category}
Brand Soul: {brand_soul}
{season_line}

Output a Visual Brief with these fields:
- surface_material: What physical surface should the product sit on to look authentic?
- environment: Describe the blurred background atmosphere (NOT a sharp detailed scene).
- lighting_scheme: Define the light source, direction, and shadow quality.
- color_palette: 3 color names or hex codes that complement the product packaging.
- suggested_props: Physical objects that complement this product (ingredients, textures, seasonal elements)."""


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

async def generate_visual_brief(
    product_name: str,
    category: str = "",
    brand_soul: str = "",
    style: ImageStyle = ImageStyle.ATTRACTIVE,
    llm_service: "LLMService | None" = None,
) -> VisualBrief:
    """Generate a structured Visual Brief via LLM art direction.

    Falls back to sensible defaults if no LLM service is available.
    """
    if llm_service is None:
        logger.warning("[ArtDirector] No LLM service; returning default brief")
        return _default_brief(product_name)

    season_line = ""
    if style == ImageStyle.SEASONAL:
        season = get_current_season()
        season_line = f"Current season: {season}. Incorporate seasonal elements."

    user_prompt = _ART_DIRECTOR_USER.format(
        style=style.value,
        product_name=product_name,
        category=category or "General",
        brand_soul=brand_soul[:300] if brand_soul else "Not specified",
        season_line=season_line,
    )

    try:
        brief = await llm_service.generate_structured(
            prompt=user_prompt,
            response_format=VisualBrief,
            system_prompt=_ART_DIRECTOR_SYSTEM,
            model="gpt-4o-mini",
            temperature=0.3,
        )
        logger.info(
            "[ArtDirector] brief generated product=%s style=%s surface=%s",
            product_name[:40], style.value, brief.surface_material,
        )
        return brief

    except Exception as e:
        logger.warning("[ArtDirector] LLM failed, using defaults: %s", e)
        return _default_brief(product_name)


def _default_brief(product_name: str) -> VisualBrief:
    """Fallback brief when LLM is unavailable."""
    return VisualBrief(
        surface_material="polished light marble",
        environment="soft neutral studio backdrop",
        lighting_scheme="diffused natural light from the left with gentle shadows",
        color_palette=["warm ivory", "soft grey", "muted gold"],
        suggested_props="complementary textures and natural elements",
    )

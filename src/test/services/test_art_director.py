"""
Unit tests for Art Director service -- VisualBrief, generate_visual_brief, season helpers.

Covers:
  - VisualBrief Pydantic schema validation
  - ImageStyle enum resolution
  - get_current_season: month-to-season mapping
  - get_season_props: season-to-props mapping
  - generate_visual_brief: happy path, LLM failure fallback, no LLM service
  - _default_brief: sensible defaults
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.services.art_director import (
    ImageStyle,
    VisualBrief,
    generate_visual_brief,
    get_current_season,
    get_season_props,
    _default_brief,
)


class TestVisualBriefSchema:
    def test_valid_data(self):
        brief = VisualBrief(
            surface_material="weathered oak",
            environment="misty morning tea garden",
            lighting_scheme="warm side-lighting with long soft shadows",
            color_palette=["ivory", "grey", "gold"],
            suggested_props="roasted coffee beans, cinnamon sticks",
        )
        assert brief.surface_material == "weathered oak"
        assert brief.environment == "misty morning tea garden"
        assert len(brief.color_palette) == 3
        assert brief.suggested_props == "roasted coffee beans, cinnamon sticks"

    def test_empty_color_palette(self):
        brief = VisualBrief(
            surface_material="marble",
            environment="studio",
            lighting_scheme="diffused",
            color_palette=[],
            suggested_props="",
        )
        assert brief.color_palette == []

    def test_missing_required_field_raises(self):
        with pytest.raises(Exception):
            VisualBrief(
                surface_material="marble",
                environment="studio",
                # missing lighting_scheme, color_palette, suggested_props
            )


class TestImageStyleEnum:
    def test_informative(self):
        assert ImageStyle("informative") == ImageStyle.INFORMATIVE

    def test_minimalist(self):
        assert ImageStyle("minimalist") == ImageStyle.MINIMALIST

    def test_attractive(self):
        assert ImageStyle("attractive") == ImageStyle.ATTRACTIVE

    def test_seasonal(self):
        assert ImageStyle("seasonal") == ImageStyle.SEASONAL

    def test_monochrome(self):
        assert ImageStyle("monochrome") == ImageStyle.MONOCHROME

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            ImageStyle("nonexistent")

    def test_all_values(self):
        values = {e.value for e in ImageStyle}
        assert values == {"informative", "minimalist", "attractive", "seasonal", "monochrome"}


class TestGetCurrentSeason:
    @patch("src.ecommerce.services.art_director.date")
    def test_january_is_winter(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 15)
        assert get_current_season() == "winter"

    @patch("src.ecommerce.services.art_director.date")
    def test_february_is_winter(self, mock_date):
        mock_date.today.return_value = date(2026, 2, 10)
        assert get_current_season() == "winter"

    @patch("src.ecommerce.services.art_director.date")
    def test_march_is_spring(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 21)
        assert get_current_season() == "spring"

    @patch("src.ecommerce.services.art_director.date")
    def test_june_is_summer(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 1)
        assert get_current_season() == "summer"

    @patch("src.ecommerce.services.art_director.date")
    def test_september_is_autumn(self, mock_date):
        mock_date.today.return_value = date(2026, 9, 15)
        assert get_current_season() == "autumn"

    @patch("src.ecommerce.services.art_director.date")
    def test_december_is_winter(self, mock_date):
        mock_date.today.return_value = date(2026, 12, 25)
        assert get_current_season() == "winter"


class TestGetSeasonProps:
    def test_spring_props(self):
        props = get_season_props("spring")
        assert "cherry blossom" in props
        assert "pastel" in props

    def test_summer_props(self):
        props = get_season_props("summer")
        assert "sunflowers" in props or "citrus" in props

    def test_autumn_props(self):
        props = get_season_props("autumn")
        assert "maple" in props or "pinecones" in props

    def test_winter_props(self):
        props = get_season_props("winter")
        assert "frosted" in props or "cinnamon" in props

    def test_unknown_season_falls_back_to_spring(self):
        props = get_season_props("monsoon")
        assert props == get_season_props("spring")


class TestDefaultBrief:
    def test_returns_visual_brief(self):
        brief = _default_brief("Test Product")
        assert isinstance(brief, VisualBrief)

    def test_has_sensible_surface(self):
        brief = _default_brief("Test Product")
        assert len(brief.surface_material) > 0

    def test_has_lighting(self):
        brief = _default_brief("Test Product")
        assert "light" in brief.lighting_scheme.lower()

    def test_has_three_colors(self):
        brief = _default_brief("Test Product")
        assert len(brief.color_palette) == 3

    def test_has_environment(self):
        brief = _default_brief("Test Product")
        assert len(brief.environment) > 0


class TestGenerateVisualBrief:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        expected_brief = VisualBrief(
            surface_material="polished marble",
            environment="soft studio backdrop",
            lighting_scheme="diffused natural light",
            color_palette=["ivory", "grey", "gold"],
            suggested_props="coffee beans, cinnamon sticks",
        )
        llm_service = MagicMock()
        llm_service.generate_structured = AsyncMock(return_value=expected_brief)

        result = await generate_visual_brief(
            product_name="Artisan Coffee",
            category="Beverage",
            brand_soul="Japanese minimalist",
            style=ImageStyle.ATTRACTIVE,
            llm_service=llm_service,
        )

        assert result == expected_brief
        llm_service.generate_structured.assert_called_once()
        call_kwargs = llm_service.generate_structured.call_args.kwargs
        assert call_kwargs["response_format"] is VisualBrief
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert "Artisan Coffee" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_llm_failure_returns_default(self):
        llm_service = MagicMock()
        llm_service.generate_structured = AsyncMock(
            side_effect=RuntimeError("LLM is down")
        )

        result = await generate_visual_brief(
            product_name="Artisan Coffee",
            llm_service=llm_service,
        )

        assert isinstance(result, VisualBrief)
        assert result.surface_material == _default_brief("").surface_material

    @pytest.mark.asyncio
    async def test_no_llm_service_returns_default(self):
        result = await generate_visual_brief(
            product_name="Artisan Coffee",
            llm_service=None,
        )

        assert isinstance(result, VisualBrief)
        assert result.surface_material == _default_brief("").surface_material

    @pytest.mark.asyncio
    async def test_seasonal_style_includes_season_in_prompt(self):
        llm_service = MagicMock()
        llm_service.generate_structured = AsyncMock(
            return_value=_default_brief("test")
        )

        await generate_visual_brief(
            product_name="Coffee",
            style=ImageStyle.SEASONAL,
            llm_service=llm_service,
        )

        call_kwargs = llm_service.generate_structured.call_args.kwargs
        assert "season" in call_kwargs["prompt"].lower()

    @pytest.mark.asyncio
    async def test_brand_soul_passed_to_prompt(self):
        llm_service = MagicMock()
        llm_service.generate_structured = AsyncMock(
            return_value=_default_brief("test")
        )

        await generate_visual_brief(
            product_name="Coffee",
            brand_soul="Modern minimalist Japanese",
            llm_service=llm_service,
        )

        call_kwargs = llm_service.generate_structured.call_args.kwargs
        assert "Modern minimalist Japanese" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_brand_soul_truncated(self):
        llm_service = MagicMock()
        llm_service.generate_structured = AsyncMock(
            return_value=_default_brief("test")
        )

        long_soul = "A" * 500
        await generate_visual_brief(
            product_name="Coffee",
            brand_soul=long_soul,
            llm_service=llm_service,
        )

        call_kwargs = llm_service.generate_structured.call_args.kwargs
        assert "A" * 300 in call_kwargs["prompt"]
        assert "A" * 301 not in call_kwargs["prompt"]

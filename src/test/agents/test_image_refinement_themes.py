"""
Unit tests for Image Refinement themed prompts.

Covers:
  - build_nano_banana_refinement_prompt() with each theme
  - Unknown theme falls back to clean
  - Brand soul injection across themes
  - ImageRefinementAgent reads refinement_theme from raw_input
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.ecommerce.agents.visual.prompts import (
    build_nano_banana_refinement_prompt,
    REFINEMENT_FIDELITY_PREAMBLE,
    REFINEMENT_THEME_TEMPLATES,
)
from src.ecommerce.agents.image_refinement.agent import ImageRefinementAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext


# =============================================================================
# Prompt builder tests
# =============================================================================

class TestBuildRefinementPrompt:
    def test_clean_theme_matches_studio_background(self):
        prompt = build_nano_banana_refinement_prompt(theme="clean")
        assert "CRITICAL FIDELITY RULES" in prompt
        assert "white or light grey" in prompt.lower() or "studio" in prompt.lower()

    def test_lifestyle_theme(self):
        prompt = build_nano_banana_refinement_prompt(theme="lifestyle")
        assert "CRITICAL FIDELITY RULES" in prompt
        assert "realistic" in prompt.lower()
        assert "lived-in" in prompt.lower() or "lifestyle" in prompt.lower()

    def test_natural_theme(self):
        prompt = build_nano_banana_refinement_prompt(theme="natural")
        assert "CRITICAL FIDELITY RULES" in prompt
        assert "natural surface" in prompt.lower() or "wabi-sabi" in prompt.lower()

    def test_premium_theme(self):
        prompt = build_nano_banana_refinement_prompt(theme="premium")
        assert "CRITICAL FIDELITY RULES" in prompt
        assert "dark" in prompt.lower() or "luxurious" in prompt.lower()
        assert "dramatic" in prompt.lower()

    def test_seasonal_theme(self):
        prompt = build_nano_banana_refinement_prompt(theme="seasonal")
        assert "CRITICAL FIDELITY RULES" in prompt
        assert "seasonal" in prompt.lower()
        # Should contain one of the season descriptions
        assert any(kw in prompt.lower() for kw in [
            "cherry blossom", "citrus", "amber leaves", "pine sprigs",
            "blossoms", "sunlight", "warm", "snow",
        ])

    def test_minimalist_theme(self):
        prompt = build_nano_banana_refinement_prompt(theme="minimalist")
        assert "CRITICAL FIDELITY RULES" in prompt
        assert "matte concrete" in prompt.lower() or "geometric shadow" in prompt.lower()

    def test_unknown_theme_falls_back_to_clean(self):
        prompt = build_nano_banana_refinement_prompt(theme="nonexistent_theme")
        clean_prompt = build_nano_banana_refinement_prompt(theme="clean")
        assert prompt == clean_prompt

    def test_with_brand_soul_injects_aesthetic(self):
        brand_soul = "Traditional Japanese artisan craftsmanship with warm earth tones"
        for theme_id in REFINEMENT_THEME_TEMPLATES:
            prompt = build_nano_banana_refinement_prompt(
                brand_soul=brand_soul,
                theme=theme_id,
            )
            assert "aesthetic" in prompt.lower()

    def test_empty_brand_soul_no_aesthetic(self):
        prompt = build_nano_banana_refinement_prompt(brand_soul="", theme="clean")
        assert "aesthetic" not in prompt.lower()

    def test_default_theme_is_clean(self):
        prompt_default = build_nano_banana_refinement_prompt()
        prompt_clean = build_nano_banana_refinement_prompt(theme="clean")
        assert prompt_default == prompt_clean

    def test_all_themes_share_fidelity_preamble(self):
        for theme_id in REFINEMENT_THEME_TEMPLATES:
            prompt = build_nano_banana_refinement_prompt(theme=theme_id)
            assert "100% fidelity" in prompt
            assert "Do NOT alter" in prompt

    def test_all_themes_have_no_text_instruction(self):
        for theme_id in REFINEMENT_THEME_TEMPLATES:
            prompt = build_nano_banana_refinement_prompt(theme=theme_id)
            assert "No added text or graphics" in prompt or "No harsh shadows. No added text" in prompt


# =============================================================================
# Agent integration: reads theme from raw_input
# =============================================================================

class TestImageRefinementAgentTheme:
    @pytest.fixture
    def mock_services(self):
        services = MagicMock()
        services.rag.get_strategic_intelligence = AsyncMock(return_value=None)
        services.rag.get_brand_context = AsyncMock(return_value=[])
        return services

    @pytest.mark.asyncio
    async def test_refinement_agent_reads_theme_from_raw_input(self, mock_services):
        agent = ImageRefinementAgent("test-shop.myshopify.com", services=mock_services)
        state = MissionState(
            product_id="product-123",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": "Test Product",
                "image_url": "https://cdn.shopify.com/product.jpg",
                "refinement_theme": "premium",
            },
        )

        context = await agent.perceive(state)
        assert context.external_data["refinement_theme"] == "premium"

    @pytest.mark.asyncio
    async def test_refinement_agent_defaults_to_clean(self, mock_services):
        agent = ImageRefinementAgent("test-shop.myshopify.com", services=mock_services)
        state = MissionState(
            product_id="product-123",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": "Test Product",
                "image_url": "https://cdn.shopify.com/product.jpg",
            },
        )

        context = await agent.perceive(state)
        assert context.external_data["refinement_theme"] == "clean"

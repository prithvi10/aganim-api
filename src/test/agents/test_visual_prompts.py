"""
Unit tests for Visual agent prompt template builders.

Covers:
  - build_inpaint_prompt: with/without brand soul and extra context
  - build_ad_prompt: with/without brand name, hook text, brand soul
  - build_hero_prompt: with/without brand soul and extra context
  - Edge cases: empty strings, very long inputs (truncation)
"""

import pytest

from src.ecommerce.agents.visual.prompts import (
    build_inpaint_prompt,
    build_ad_prompt,
    build_hero_prompt,
    INPAINT_BACKGROUND_PROMPT_TEMPLATE,
    AD_COMPOSITION_PROMPT_TEMPLATE,
    HERO_BANNER_PROMPT_TEMPLATE,
)


# =============================================================================
# Tests: build_inpaint_prompt
# =============================================================================

class TestBuildInpaintPrompt:
    """Test build_inpaint_prompt."""

    def test_with_brand_soul(self):
        prompt = build_inpaint_prompt(brand_soul="Minimalist Kyoto zen")
        assert "Minimalist Kyoto zen" in prompt
        assert "brand identity" in prompt.lower()
        assert "Professional product photography" in prompt

    def test_without_brand_soul(self):
        prompt = build_inpaint_prompt()
        assert "Brand aesthetic" not in prompt
        assert "Professional product photography" in prompt

    def test_empty_brand_soul(self):
        prompt = build_inpaint_prompt(brand_soul="")
        assert "Brand aesthetic" not in prompt

    def test_with_extra_context(self):
        prompt = build_inpaint_prompt(extra_context="Use warm lighting")
        assert "warm lighting" in prompt

    def test_brand_soul_truncated_at_500(self):
        long_soul = "A" * 1000
        prompt = build_inpaint_prompt(brand_soul=long_soul)
        # The brand soul should be truncated to 500 chars
        assert "A" * 500 in prompt
        assert "A" * 501 not in prompt

    def test_combined_inputs(self):
        prompt = build_inpaint_prompt(
            brand_soul="Japanese ceramics",
            extra_context="Outdoor setting",
        )
        assert "Japanese ceramics" in prompt
        assert "Outdoor setting" in prompt

    def test_result_is_stripped(self):
        prompt = build_inpaint_prompt()
        assert not prompt.startswith("\n")
        assert not prompt.endswith("\n")


# =============================================================================
# Tests: build_ad_prompt
# =============================================================================

class TestBuildAdPrompt:
    """Test build_ad_prompt."""

    def test_full_inputs(self):
        prompt = build_ad_prompt(
            product_name="Ceramic Bowl",
            hook_text="New Collection",
            brand_name="Kyoto Artisan",
            brand_soul="Traditional Japanese craftsmanship",
        )
        assert "Ceramic Bowl" in prompt
        assert "New Collection" in prompt
        assert "Kyoto Artisan" in prompt
        assert "Traditional Japanese" in prompt

    def test_no_brand_name(self):
        prompt = build_ad_prompt(
            product_name="Bowl",
            hook_text="Limited Edition",
        )
        assert "Limited Edition" in prompt
        assert "brand name" not in prompt.lower()

    def test_no_brand_soul(self):
        prompt = build_ad_prompt(
            product_name="Bowl",
            hook_text="Summer Sale",
        )
        assert "Brand aesthetic" not in prompt

    def test_brand_soul_truncated_at_300(self):
        long_soul = "B" * 600
        prompt = build_ad_prompt(
            product_name="Bowl",
            hook_text="Test",
            brand_soul=long_soul,
        )
        assert "B" * 300 in prompt
        assert "B" * 301 not in prompt

    def test_result_is_stripped(self):
        prompt = build_ad_prompt(product_name="X", hook_text="Y")
        assert not prompt.startswith("\n")
        assert not prompt.endswith("\n")

    def test_instagram_format_mention(self):
        prompt = build_ad_prompt(product_name="Bowl", hook_text="Test")
        assert "Instagram" in prompt


# =============================================================================
# Tests: build_hero_prompt
# =============================================================================

class TestBuildHeroPrompt:
    """Test build_hero_prompt."""

    def test_with_brand_soul(self):
        prompt = build_hero_prompt(brand_soul="Zen garden vibes")
        assert "Zen garden vibes" in prompt
        assert "visual consistency" in prompt.lower()

    def test_without_brand_soul(self):
        prompt = build_hero_prompt()
        assert "Brand aesthetic" not in prompt
        assert "16:9" in prompt

    def test_with_extra_context(self):
        prompt = build_hero_prompt(extra_context="Include sakura blossoms")
        assert "sakura blossoms" in prompt

    def test_brand_soul_truncated_at_500(self):
        long_soul = "C" * 1000
        prompt = build_hero_prompt(brand_soul=long_soul)
        assert "C" * 500 in prompt
        assert "C" * 501 not in prompt

    def test_hero_mentions_collection_page(self):
        prompt = build_hero_prompt()
        assert "collection" in prompt.lower()

    def test_hero_mentions_blog(self):
        prompt = build_hero_prompt()
        assert "blog" in prompt.lower()

    def test_result_is_stripped(self):
        prompt = build_hero_prompt()
        assert not prompt.startswith("\n")
        assert not prompt.endswith("\n")


# =============================================================================
# Tests: Template constants exist and contain expected placeholders
# =============================================================================

class TestTemplateConstants:
    """Test that template constants have the expected structure."""

    def test_inpaint_template_has_placeholders(self):
        assert "{brand_style}" in INPAINT_BACKGROUND_PROMPT_TEMPLATE
        assert "{extra_context}" in INPAINT_BACKGROUND_PROMPT_TEMPLATE

    def test_ad_template_has_placeholders(self):
        assert "{product_name}" in AD_COMPOSITION_PROMPT_TEMPLATE
        assert "{hook_text}" in AD_COMPOSITION_PROMPT_TEMPLATE
        assert "{brand_name_line}" in AD_COMPOSITION_PROMPT_TEMPLATE
        assert "{brand_style}" in AD_COMPOSITION_PROMPT_TEMPLATE

    def test_hero_template_has_placeholders(self):
        assert "{brand_style}" in HERO_BANNER_PROMPT_TEMPLATE
        assert "{extra_context}" in HERO_BANNER_PROMPT_TEMPLATE
        assert "16:9" in HERO_BANNER_PROMPT_TEMPLATE

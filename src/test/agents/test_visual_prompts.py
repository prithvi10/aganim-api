"""
Unit tests for Visual agent prompt template builders.

Covers:
  - build_inpaint_prompt: with/without brand soul and extra context
  - build_ad_prompt: with/without brand name, hook text, brand soul
  - build_hero_prompt: with/without brand soul and extra context
  - Edge cases: empty strings, very long inputs (truncation)
  - Art-Directed style templates (Informative, Minimalist, Attractive, Seasonal)
  - build_styled_prompt: all 4 styles, logo logic, season injection, fallback
  - Updated hero templates: photorealism directives
"""

import pytest

from src.ecommerce.agents.visual.prompts import (
    build_inpaint_prompt,
    build_ad_prompt,
    build_hero_prompt,
    build_collection_hero_prompt,
    build_blog_hero_prompt,
    build_hero_section_prompt,
    build_styled_prompt,
    build_blog_hero_from_brief,
    _distill_brand_aesthetic,
    _HERO_PROMPT_HARD_CAP,
    INPAINT_BACKGROUND_PROMPT_TEMPLATE,
    AD_COMPOSITION_PROMPT_TEMPLATE,
    HERO_BANNER_PROMPT_TEMPLATE,
    COLLECTION_HERO_TEMPLATE,
    BLOG_HERO_TEMPLATE,
    HERO_SECTION_TEMPLATE,
    INFORMATIVE_STYLE_TEMPLATE,
    MINIMALIST_STYLE_TEMPLATE,
    ATTRACTIVE_STYLE_TEMPLATE,
    SEASONAL_STYLE_TEMPLATE,
    MONOCHROME_STYLE_TEMPLATE,
)
from src.ecommerce.services.art_director import VisualBrief


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

    def test_brand_soul_truncated(self):
        long_soul = "B" * 600
        prompt = build_ad_prompt(
            product_name="Bowl",
            hook_text="Test",
            brand_soul=long_soul,
        )
        assert "B" * 200 in prompt
        assert "B" * 201 not in prompt

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
        assert "Brand aesthetic" in prompt

    def test_without_brand_soul(self):
        prompt = build_hero_prompt()
        assert "Brand aesthetic" not in prompt
        assert "16:9" in prompt

    def test_with_extra_context(self):
        prompt = build_hero_prompt(extra_context="Include sakura blossoms")
        assert "sakura blossoms" in prompt

    def test_brand_soul_distilled_to_120_chars(self):
        long_soul = "C" * 1000
        prompt = build_hero_prompt(brand_soul=long_soul)
        # Brand aesthetic is distilled to max 120 chars, not dumped raw
        assert "C" * 120 in prompt
        assert "C" * 121 not in prompt

    def test_total_prompt_never_exceeds_500_chars(self):
        long_soul = "Very important brand " * 50
        prompt = build_hero_prompt(brand_soul=long_soul)
        assert len(prompt) <= _HERO_PROMPT_HARD_CAP

    def test_dict_brand_soul_distilled(self):
        dict_soul = str({
            "archetype": "innovative_pioneer",
            "power_words": ["innovation", "tradition", "surprise", "excitement", "essence",
                            "freshness", "quality", "culture"],
            "banned_phrases": ["ordinary", "mass-produced"],
        })
        prompt = build_hero_prompt(brand_soul=dict_soul)
        assert "Innovative Pioneer" in prompt
        assert "innovation" in prompt
        assert len(prompt) <= _HERO_PROMPT_HARD_CAP
        # Raw dict syntax should NOT leak into the prompt
        assert "banned_phrases" not in prompt

    def test_hero_mentions_banner(self):
        prompt = build_hero_prompt()
        assert "hero banner" in prompt.lower()

    def test_hero_no_text_instruction(self):
        prompt = build_hero_prompt()
        assert "no text" in prompt.lower()

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


# =============================================================================
# Tests: _distill_brand_aesthetic (helper)
# =============================================================================

class TestDistillBrandAesthetic:
    """Test _distill_brand_aesthetic extracts concise visual hints."""

    def test_empty_string(self):
        assert _distill_brand_aesthetic("") == ""

    def test_plain_text_returned_as_is(self):
        assert _distill_brand_aesthetic("Minimalist Kyoto zen") == "Minimalist Kyoto zen"

    def test_plain_text_truncated_to_max_len(self):
        result = _distill_brand_aesthetic("A" * 200, max_len=50)
        assert len(result) == 50

    def test_dict_extracts_archetype(self):
        soul = str({"archetype": "artisan_master", "power_words": []})
        result = _distill_brand_aesthetic(soul)
        assert "Artisan Master" in result

    def test_dict_extracts_power_words(self):
        soul = str({
            "archetype": "heritage_house",
            "power_words": ["handcrafted", "heritage", "artisan", "heirloom", "kiln-fired",
                            "provenance", "timeless"],
        })
        result = _distill_brand_aesthetic(soul)
        assert "Heritage House" in result
        assert "handcrafted" in result
        # Only first 5 power words should be included
        assert "provenance" not in result
        assert "timeless" not in result

    def test_dict_respects_max_len(self):
        soul = str({
            "archetype": "innovative_pioneer",
            "power_words": ["word"] * 20,
        })
        result = _distill_brand_aesthetic(soul, max_len=40)
        assert len(result) <= 40

    def test_dict_without_archetype(self):
        soul = str({"power_words": ["fresh", "bold"]})
        result = _distill_brand_aesthetic(soul)
        assert "fresh" in result

    def test_dict_without_power_words(self):
        soul = str({"archetype": "storyteller"})
        result = _distill_brand_aesthetic(soul)
        assert "Storyteller" in result

    def test_malformed_dict_string_returns_empty(self):
        result = _distill_brand_aesthetic("{'broken: dict")
        assert result == ""

    def test_whitespace_collapsed_in_plain_text(self):
        result = _distill_brand_aesthetic("  lots   of   spaces  ")
        assert "  " not in result


# =============================================================================
# Tests: Hero prompt templates (Nano Banana text-to-image)
# =============================================================================

class TestHeroPromptTemplateConstants:
    """Test that hero prompt template constants have expected placeholders."""

    def test_collection_template_has_placeholders(self):
        assert "{collection_name}" in COLLECTION_HERO_TEMPLATE
        assert "{description_line}" in COLLECTION_HERO_TEMPLATE
        assert "{products_line}" in COLLECTION_HERO_TEMPLATE
        assert "{brand_style}" in COLLECTION_HERO_TEMPLATE

    def test_blog_template_has_placeholders(self):
        assert "{subject}" in BLOG_HERO_TEMPLATE
        assert "{category}" in BLOG_HERO_TEMPLATE
        assert "{context_line}" in BLOG_HERO_TEMPLATE
        assert "{brand_style}" in BLOG_HERO_TEMPLATE

    def test_hero_section_template_has_placeholders(self):
        assert "{subject}" in HERO_SECTION_TEMPLATE
        assert "{description_line}" in HERO_SECTION_TEMPLATE
        assert "{brand_style}" in HERO_SECTION_TEMPLATE


class TestBuildCollectionHeroPrompt:
    """Test build_collection_hero_prompt."""

    def test_basic(self):
        prompt = build_collection_hero_prompt(collection_name="Summer Sake")
        assert "Summer Sake" in prompt
        assert "no text" in prompt.lower()
        assert "collection" in prompt.lower()

    def test_with_description(self):
        prompt = build_collection_hero_prompt(
            collection_name="Summer Sake",
            description="Our best summer picks",
        )
        assert "summer picks" in prompt.lower()

    def test_with_product_names(self):
        prompt = build_collection_hero_prompt(
            collection_name="Summer Sake",
            product_names=["Yuzu Sake", "Plum Sake"],
        )
        assert "Yuzu Sake" in prompt
        assert "Plum Sake" in prompt

    def test_product_names_capped_at_8(self):
        names = [f"Product {i}" for i in range(12)]
        prompt = build_collection_hero_prompt(
            collection_name="Big Collection",
            product_names=names,
        )
        assert "Product 7" in prompt
        assert "Product 8" not in prompt

    def test_with_brand_soul(self):
        prompt = build_collection_hero_prompt(
            collection_name="Artisan",
            brand_soul="Minimalist Kyoto zen",
        )
        assert "Minimalist Kyoto zen" in prompt

    def test_without_brand_soul(self):
        prompt = build_collection_hero_prompt(collection_name="Test")
        assert "aesthetic" not in prompt.lower()

    def test_result_is_stripped(self):
        prompt = build_collection_hero_prompt(collection_name="Test")
        assert not prompt.startswith("\n")
        assert not prompt.endswith("\n")


class TestBuildBlogHeroPrompt:
    """Test build_blog_hero_prompt."""

    def test_basic(self):
        prompt = build_blog_hero_prompt(subject="Japanese ceramics")
        assert "Japanese ceramics" in prompt
        assert "no text" in prompt.lower()
        assert "blog" in prompt.lower()

    def test_with_category(self):
        prompt = build_blog_hero_prompt(
            subject="Kiln firing",
            category="Manufacturing",
        )
        assert "Manufacturing" in prompt

    def test_with_context(self):
        prompt = build_blog_hero_prompt(
            subject="Our story",
            context="Founded in 1920",
        )
        assert "1920" in prompt

    def test_with_brand_soul(self):
        prompt = build_blog_hero_prompt(
            subject="Tea ceremony",
            brand_soul="Traditional Japanese artisan",
        )
        assert "Traditional Japanese artisan" in prompt

    def test_result_is_stripped(self):
        prompt = build_blog_hero_prompt(subject="Test")
        assert not prompt.startswith("\n")
        assert not prompt.endswith("\n")


class TestBuildHeroSectionPrompt:
    """Test build_hero_section_prompt."""

    def test_basic(self):
        prompt = build_hero_section_prompt(subject="Spring Flowers")
        assert "Spring Flowers" in prompt
        assert "no text" in prompt.lower()
        assert "hero banner" in prompt.lower()

    def test_with_short_description(self):
        prompt = build_hero_section_prompt(
            subject="Winter Sale",
            short_description="50% off everything",
        )
        assert "50% off" in prompt

    def test_with_brand_soul(self):
        prompt = build_hero_section_prompt(
            subject="Beach Vibes",
            brand_soul="Modern coastal lifestyle",
        )
        assert "Modern coastal lifestyle" in prompt

    def test_without_short_description(self):
        prompt = build_hero_section_prompt(subject="Mountains")
        assert "description" not in prompt.lower() or "description_line" not in prompt

    def test_result_is_stripped(self):
        prompt = build_hero_section_prompt(subject="Test")
        assert not prompt.startswith("\n")
        assert not prompt.endswith("\n")


# =============================================================================
# Tests: Art-Directed Style Template Constants
# =============================================================================

_MOCK_BRIEF = VisualBrief(
    surface_material="polished marble",
    environment="soft studio backdrop",
    lighting_scheme="diffused natural light from the left",
    color_palette=["ivory", "grey", "gold"],
    suggested_props="coffee beans, cinnamon sticks",
)


class TestStyledPromptTemplateConstants:
    """Verify all 4 style templates contain expected placeholders."""

    def test_informative_placeholders(self):
        assert "{surface_material}" in INFORMATIVE_STYLE_TEMPLATE
        assert "{lighting_scheme}" in INFORMATIVE_STYLE_TEMPLATE
        assert "{environment}" in INFORMATIVE_STYLE_TEMPLATE
        assert "{color_palette}" in INFORMATIVE_STYLE_TEMPLATE
        assert "{product_name}" in INFORMATIVE_STYLE_TEMPLATE
        assert "{logo_line}" in INFORMATIVE_STYLE_TEMPLATE

    def test_minimalist_placeholders(self):
        assert "{surface_material}" in MINIMALIST_STYLE_TEMPLATE
        assert "{lighting_scheme}" in MINIMALIST_STYLE_TEMPLATE
        assert "{color_palette}" in MINIMALIST_STYLE_TEMPLATE

    def test_attractive_placeholders(self):
        assert "{surface_material}" in ATTRACTIVE_STYLE_TEMPLATE
        assert "{lighting_scheme}" in ATTRACTIVE_STYLE_TEMPLATE
        assert "{environment}" in ATTRACTIVE_STYLE_TEMPLATE
        assert "{color_palette}" in ATTRACTIVE_STYLE_TEMPLATE
        assert "{suggested_props}" in ATTRACTIVE_STYLE_TEMPLATE

    def test_seasonal_placeholders(self):
        assert "{surface_material}" in SEASONAL_STYLE_TEMPLATE
        assert "{lighting_scheme}" in SEASONAL_STYLE_TEMPLATE
        assert "{environment}" in SEASONAL_STYLE_TEMPLATE
        assert "{color_palette}" in SEASONAL_STYLE_TEMPLATE
        assert "{season}" in SEASONAL_STYLE_TEMPLATE
        assert "{season_props}" in SEASONAL_STYLE_TEMPLATE


class TestBuildStyledPrompt:
    """Test build_styled_prompt for all 4 styles."""

    def test_attractive_style(self):
        prompt = build_styled_prompt(
            style="attractive",
            brief=_MOCK_BRIEF,
            product_name="Artisan Coffee",
        )
        assert "polished marble" in prompt
        assert "coffee beans" in prompt
        assert "diffused natural light" in prompt
        assert "NOT illustrated" in prompt

    def test_minimalist_style(self):
        prompt = build_styled_prompt(
            style="minimalist",
            brief=_MOCK_BRIEF,
            product_name="Artisan Coffee",
        )
        assert "polished marble" in prompt
        assert "No props" in prompt
        assert "no text" in prompt.lower() or "No props" in prompt

    def test_informative_with_brand_name(self):
        prompt = build_styled_prompt(
            style="informative",
            brief=_MOCK_BRIEF,
            product_name="Artisan Coffee",
            brand_name="Kyoto Brews",
        )
        assert "Artisan Coffee" in prompt
        assert "Kyoto Brews" in prompt
        assert "logo" in prompt.lower()

    def test_informative_without_brand_name_omits_logo(self):
        prompt = build_styled_prompt(
            style="informative",
            brief=_MOCK_BRIEF,
            product_name="Artisan Coffee",
            brand_name="",
        )
        assert "Artisan Coffee" in prompt
        assert "logo" not in prompt.lower()

    def test_seasonal_includes_season(self):
        prompt = build_styled_prompt(
            style="seasonal",
            brief=_MOCK_BRIEF,
            product_name="Artisan Coffee",
            season="winter",
            season_props="frosted pine branches, cinnamon sticks",
        )
        assert "winter" in prompt
        assert "frosted pine" in prompt

    def test_seasonal_without_season_defaults(self):
        prompt = build_styled_prompt(
            style="seasonal",
            brief=_MOCK_BRIEF,
            product_name="Coffee",
        )
        assert "spring" in prompt

    def test_unknown_style_falls_back_to_attractive(self):
        prompt = build_styled_prompt(
            style="nonexistent",
            brief=_MOCK_BRIEF,
            product_name="Coffee",
        )
        assert "coffee beans" in prompt
        assert "polished marble" in prompt

    def test_result_is_stripped(self):
        prompt = build_styled_prompt(
            style="attractive",
            brief=_MOCK_BRIEF,
            product_name="Coffee",
        )
        assert not prompt.startswith("\n")
        assert not prompt.endswith("\n")

    def test_color_palette_joined(self):
        prompt = build_styled_prompt(
            style="attractive",
            brief=_MOCK_BRIEF,
            product_name="Coffee",
        )
        assert "ivory, grey, gold" in prompt

    def test_img2img_adds_fidelity_preamble(self):
        prompt = build_styled_prompt(
            style="attractive",
            brief=_MOCK_BRIEF,
            product_name="Coffee",
            is_img2img=True,
        )
        assert "EXACT product from the reference image" in prompt
        assert "Preserve it faithfully" in prompt
        assert "same shape, colors, labels" in prompt

    def test_t2i_no_fidelity_preamble(self):
        prompt = build_styled_prompt(
            style="attractive",
            brief=_MOCK_BRIEF,
            product_name="Coffee",
            is_img2img=False,
        )
        assert "reference image" not in prompt

    def test_img2img_fidelity_with_all_styles(self):
        for style in ("informative", "minimalist", "attractive", "seasonal", "monochrome"):
            prompt = build_styled_prompt(
                style=style,
                brief=_MOCK_BRIEF,
                product_name="Coffee",
                brand_name="TestBrand",
                season="winter",
                season_props="frosted pine",
                is_img2img=True,
            )
            assert "EXACT product from the reference image" in prompt, f"Fidelity preamble missing for style={style}"


class TestUpdatedHeroTemplates:
    """Verify updated hero templates contain photorealism directives."""

    def test_collection_hero_photorealism(self):
        assert "Photorealistic" in COLLECTION_HERO_TEMPLATE
        assert "shallow depth of field" in COLLECTION_HERO_TEMPLATE.lower()
        assert "NOT illustrated, cartoon" in COLLECTION_HERO_TEMPLATE

    def test_blog_hero_photorealism(self):
        assert "Photorealistic" in BLOG_HERO_TEMPLATE
        assert "shallow depth of field" in BLOG_HERO_TEMPLATE.lower()
        assert "NOT illustrated, cartoon" in BLOG_HERO_TEMPLATE

    def test_hero_section_photorealism(self):
        assert "Photorealistic" in HERO_SECTION_TEMPLATE
        assert "shallow depth of field" in HERO_SECTION_TEMPLATE.lower()
        assert "NOT illustrated, cartoon" in HERO_SECTION_TEMPLATE

    def test_hero_banner_photorealism(self):
        assert "Photorealistic" in HERO_BANNER_PROMPT_TEMPLATE
        assert "shallow depth of field" in HERO_BANNER_PROMPT_TEMPLATE.lower()
        assert "NOT illustrated, cartoon" in HERO_BANNER_PROMPT_TEMPLATE


# =============================================================================
# Tests: Monochrome style template
# =============================================================================

class TestMonochromeStyleTemplate:
    """Tests for the MONOCHROME_STYLE_TEMPLATE and its integration."""

    def test_monochrome_template_has_placeholders(self):
        assert "{hero_subject}" in MONOCHROME_STYLE_TEMPLATE
        assert "{surface_material}" in MONOCHROME_STYLE_TEMPLATE
        assert "{environment}" in MONOCHROME_STYLE_TEMPLATE
        assert "{lighting_scheme}" in MONOCHROME_STYLE_TEMPLATE

    def test_monochrome_template_has_bw_directives(self):
        assert "Black and white" in MONOCHROME_STYLE_TEMPLATE
        assert "Monochrome" in MONOCHROME_STYLE_TEMPLATE
        assert "No color" in MONOCHROME_STYLE_TEMPLATE

    def test_monochrome_template_has_photorealism(self):
        assert "NOT illustrated, cartoon" in MONOCHROME_STYLE_TEMPLATE

    def test_build_styled_prompt_monochrome(self):
        prompt = build_styled_prompt(
            style="monochrome",
            brief=_MOCK_BRIEF,
            product_name="Artisan Coffee",
        )
        assert "Black and white" in prompt
        assert "polished marble" in prompt
        assert "Monochrome" in prompt
        assert "NOT illustrated" in prompt

    def test_monochrome_img2img_adds_fidelity(self):
        prompt = build_styled_prompt(
            style="monochrome",
            brief=_MOCK_BRIEF,
            product_name="Coffee",
            is_img2img=True,
        )
        assert "EXACT product from the reference image" in prompt
        assert "Black and white" in prompt


# =============================================================================
# Tests: build_blog_hero_from_brief
# =============================================================================

_MOCK_BLOG_VISUAL_BRIEF = {
    "hero_subject": "Close-up of steam rising from a freshly poured cup of dark coffee",
    "surface": "A rustic, weathered oak tabletop",
    "environment": "A softly blurred, sunlit minimalist kitchen corner",
    "lighting": "Soft side-lighting with gentle, long shadows",
}


class TestBuildBlogHeroFromBrief:
    """Tests for build_blog_hero_from_brief."""

    def test_default_style_produces_editorial_prompt(self):
        prompt = build_blog_hero_from_brief(_MOCK_BLOG_VISUAL_BRIEF)
        assert "steam rising" in prompt
        assert "weathered oak" in prompt
        assert "sunlit minimalist kitchen" in prompt
        assert "Soft side-lighting" in prompt

    def test_no_humans_directive(self):
        prompt = build_blog_hero_from_brief(_MOCK_BLOG_VISUAL_BRIEF)
        assert "No actors" in prompt or "no faces" in prompt.lower() or "no human" in prompt.lower()

    def test_photorealism_directive(self):
        prompt = build_blog_hero_from_brief(_MOCK_BLOG_VISUAL_BRIEF)
        assert "NOT illustrated" in prompt

    def test_monochrome_style_uses_bw_template(self):
        prompt = build_blog_hero_from_brief(
            _MOCK_BLOG_VISUAL_BRIEF,
            image_style="monochrome",
        )
        assert "Black and white" in prompt
        assert "Monochrome" in prompt
        assert "No color" in prompt
        assert "steam rising" in prompt

    def test_attractive_style_uses_base_template(self):
        prompt = build_blog_hero_from_brief(
            _MOCK_BLOG_VISUAL_BRIEF,
            image_style="attractive",
        )
        assert "Black and white" not in prompt
        assert "steam rising" in prompt

    def test_img2img_adds_fidelity_preamble(self):
        prompt = build_blog_hero_from_brief(
            _MOCK_BLOG_VISUAL_BRIEF,
            is_img2img=True,
        )
        assert "EXACT product from the reference image" in prompt

    def test_t2i_no_fidelity_preamble(self):
        prompt = build_blog_hero_from_brief(
            _MOCK_BLOG_VISUAL_BRIEF,
            is_img2img=False,
        )
        assert "reference image" not in prompt

    def test_missing_keys_use_defaults(self):
        prompt = build_blog_hero_from_brief({})
        assert "product arrangement" in prompt
        assert "clean surface" in prompt
        assert "soft neutral backdrop" in prompt

    def test_partial_brief(self):
        partial = {"hero_subject": "A single ceramic cup"}
        prompt = build_blog_hero_from_brief(partial)
        assert "ceramic cup" in prompt
        assert "clean surface" in prompt

    def test_result_is_stripped(self):
        prompt = build_blog_hero_from_brief(_MOCK_BLOG_VISUAL_BRIEF)
        assert not prompt.startswith("\n")
        assert not prompt.endswith("\n")

    def test_monochrome_img2img_combined(self):
        prompt = build_blog_hero_from_brief(
            _MOCK_BLOG_VISUAL_BRIEF,
            image_style="monochrome",
            is_img2img=True,
        )
        assert "Black and white" in prompt
        assert "EXACT product from the reference image" in prompt

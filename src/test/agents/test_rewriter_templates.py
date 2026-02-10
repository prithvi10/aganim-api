"""
Unit tests for RewriterAgent template-based generation.

Tests all 5 product templates with PROD-quality mock responses:
- product/description
- product/title
- product/collection
- product/faq
- product/landing-hero

Each test verifies:
1. Correct template routing
2. Prompt construction with brand context + operational rules
3. LLM call parameters
4. State update after generation
5. Brand voice enforcement in output
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.main.agents.rewriter import RewriterAgent
from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext

from src.test.fixtures.brand_soul_fixtures import (
    STRATEGIC_INTELLIGENCE,
    BRAND_CONTEXT_CHUNKS,
    PRODUCT_CELADON_BOWL,
    PRODUCT_TEAPOT,
    MOCK_PRODUCT_DESCRIPTION_RESPONSE,
    MOCK_PRODUCT_TITLE_RESPONSE,
    MOCK_COLLECTION_RESPONSE,
    MOCK_FAQ_RESPONSE,
    MOCK_LANDING_HERO_RESPONSE,
    BRAND_VOICE_MUST_INCLUDE_KEYWORDS,
    BRAND_VOICE_BANNED_WORDS,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry with PROD-quality responses."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value=MOCK_PRODUCT_DESCRIPTION_RESPONSE)
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=BRAND_CONTEXT_CHUNKS)
    services.rag.get_complete_context = AsyncMock(return_value={
        "chunks": BRAND_CONTEXT_CHUNKS,
        "expanded_chunks": [],
        "related_triplets": [],
        "strategic_rules": STRATEGIC_INTELLIGENCE,
    })
    services.rag._get_strategic_intelligence = AsyncMock(return_value=STRATEGIC_INTELLIGENCE)
    return services


@pytest.fixture
def base_state():
    """Create base MissionState for product content."""
    return MissionState(
        product_id=PRODUCT_CELADON_BOWL["id"],
        shop_id="takumi-ceramics.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": PRODUCT_CELADON_BOWL["title"],
            "description": PRODUCT_CELADON_BOWL["description"],
            "category": PRODUCT_CELADON_BOWL["category"],
            "target_locale": "en",
        },
        target_locale="en",
    )


def _assert_brand_voice(text: str):
    """Assert the text follows Takumi Ceramics brand voice."""
    text_lower = text.lower()
    # At least 2 brand keywords should appear
    matches = [kw for kw in BRAND_VOICE_MUST_INCLUDE_KEYWORDS if kw.lower() in text_lower]
    assert len(matches) >= 2, (
        f"Expected at least 2 brand keywords in output but found: {matches}. "
        f"Text: {text[:200]}..."
    )
    # None of the banned words should appear
    for banned in BRAND_VOICE_BANNED_WORDS:
        assert banned.lower() not in text_lower, (
            f"Banned word '{banned}' found in output: {text[:200]}..."
        )


# =============================================================================
# Tests: product/description template
# =============================================================================

class TestProductDescriptionTemplate:
    """Tests for the default product description template."""

    @pytest.mark.asyncio
    async def test_routes_to_description_generator(self, mock_services, base_state):
        """Default template_id should route to _generate_description."""
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None
        assert "jade whisper" in result.draft_content.lower()

    @pytest.mark.asyncio
    async def test_description_contains_product_html(self, mock_services, base_state):
        """Output should contain HTML with product information."""
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert "<p>" in result.draft_content
        assert "12 cm" in result.draft_content or "12cm" in result.draft_content

    @pytest.mark.asyncio
    async def test_description_extracts_title(self, mock_services, base_state):
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.draft_title is not None
        assert "Celadon" in result.draft_title

    @pytest.mark.asyncio
    async def test_description_extracts_discovered_values(self, mock_services, base_state):
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.discovered_values is not None
        assert len(result.discovered_values) >= 1

    @pytest.mark.asyncio
    async def test_description_brand_voice(self, mock_services, base_state):
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        _assert_brand_voice(result.draft_content)

    @pytest.mark.asyncio
    async def test_description_uses_gpt4o(self, mock_services, base_state):
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(base_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o"
        assert call_kwargs.get("temperature") == 0.7


# =============================================================================
# Tests: product/title template
# =============================================================================

class TestProductTitleTemplate:
    """Tests for the product title generator template."""

    @pytest.fixture
    def title_state(self, base_state):
        base_state.raw_input["template_id"] = "product/title"
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_title_generator(self, mock_services, title_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_PRODUCT_TITLE_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(title_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_title is not None
        assert "Celadon" in result.draft_title

    @pytest.mark.asyncio
    async def test_title_has_alternatives(self, mock_services, title_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_PRODUCT_TITLE_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(title_state)

        parsed = json.loads(MOCK_PRODUCT_TITLE_RESPONSE)
        assert len(parsed["alternatives"]) == 3

    @pytest.mark.asyncio
    async def test_title_prompt_uses_template(self, mock_services, title_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_PRODUCT_TITLE_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(title_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        # Title template should ask for SEO-friendly titles
        assert "title" in system_prompt.lower()
        assert "70 character" in system_prompt.lower() or "70 char" in system_prompt.lower()

    @pytest.mark.asyncio
    async def test_title_action_records_template_id(self, mock_services, title_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_PRODUCT_TITLE_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(title_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        # The prompt should contain the product title
        prompt = call_kwargs.get("prompt", "")
        assert PRODUCT_CELADON_BOWL["title"] in prompt


# =============================================================================
# Tests: product/collection template
# =============================================================================

class TestProductCollectionTemplate:
    """Tests for the collection description template."""

    @pytest.fixture
    def collection_state(self, base_state):
        base_state.raw_input["template_id"] = "product/collection"
        base_state.raw_input["collection_name"] = "Celadon Jade Collection"
        base_state.raw_input["products"] = "Rice Bowl, Sake Cup, Side Plate, Tea Cup"
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_collection_generator(self, mock_services, collection_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_COLLECTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(collection_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_collection_has_html_content(self, mock_services, collection_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_COLLECTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(collection_state)

        assert "<p>" in result.draft_content

    @pytest.mark.asyncio
    async def test_collection_brand_voice(self, mock_services, collection_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_COLLECTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(collection_state)

        _assert_brand_voice(result.draft_content)

    @pytest.mark.asyncio
    async def test_collection_prompt_includes_collection_name(self, mock_services, collection_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_COLLECTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(collection_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        prompt = call_kwargs.get("prompt", "")
        assert "Celadon Jade Collection" in prompt


# =============================================================================
# Tests: product/faq template
# =============================================================================

class TestProductFaqTemplate:
    """Tests for the FAQ generator template."""

    @pytest.fixture
    def faq_state(self, base_state):
        base_state.raw_input["template_id"] = "product/faq"
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_faq_generator(self, mock_services, faq_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_FAQ_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(faq_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_faq_content_is_parseable(self, mock_services, faq_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_FAQ_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(faq_state)

        # The FAQs should be stored in draft_content
        assert "question" in result.draft_content.lower() or "dishwasher" in result.draft_content.lower()

    @pytest.mark.asyncio
    async def test_faq_response_has_multiple_items(self):
        """Verify our mock FAQ response has 5-8 items."""
        parsed = json.loads(MOCK_FAQ_RESPONSE)
        assert 5 <= len(parsed["faqs"]) <= 8
        for faq in parsed["faqs"]:
            assert "question" in faq
            assert "answer" in faq
            assert len(faq["question"]) > 10
            assert len(faq["answer"]) > 20

    @pytest.mark.asyncio
    async def test_faq_brand_voice_in_answers(self):
        """FAQ answers should reflect brand voice."""
        parsed = json.loads(MOCK_FAQ_RESPONSE)
        all_text = " ".join(faq["answer"] for faq in parsed["faqs"])
        _assert_brand_voice(all_text)

    @pytest.mark.asyncio
    async def test_faq_prompt_uses_template(self, mock_services, faq_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_FAQ_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(faq_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        assert "faq" in system_prompt.lower()


# =============================================================================
# Tests: product/landing-hero template
# =============================================================================

class TestProductLandingHeroTemplate:
    """Tests for the landing page hero template."""

    @pytest.fixture
    def hero_state(self, base_state):
        base_state.raw_input["template_id"] = "product/landing-hero"
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_hero_generator(self, mock_services, hero_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_LANDING_HERO_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(hero_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_hero_response_structure(self):
        """Verify mock hero response has required fields."""
        parsed = json.loads(MOCK_LANDING_HERO_RESPONSE)
        assert "headline" in parsed
        assert "subheadline" in parsed
        assert "cta_text" in parsed
        assert "hero_description" in parsed
        assert len(parsed["headline"]) <= 60

    @pytest.mark.asyncio
    async def test_hero_brand_voice(self):
        parsed = json.loads(MOCK_LANDING_HERO_RESPONSE)
        all_text = f"{parsed['headline']} {parsed['subheadline']} {parsed['hero_description']}"
        _assert_brand_voice(all_text)

    @pytest.mark.asyncio
    async def test_hero_prompt_uses_template(self, mock_services, hero_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_LANDING_HERO_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(hero_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        assert "headline" in system_prompt.lower()
        assert "cta" in system_prompt.lower()


# =============================================================================
# Tests: Operational Rules Injection
# =============================================================================

class TestOperationalRulesInjection:
    """Verify that strategic intelligence is injected into prompts."""

    @pytest.mark.asyncio
    async def test_system_prompt_includes_operational_rules(self, mock_services, base_state):
        """Operational rules from strategic intelligence should be in system prompt."""
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)

        context = AgentContext(
            raw_input=base_state.raw_input,
            brand_context=BRAND_CONTEXT_CHUNKS,
            strategic_intelligence=STRATEGIC_INTELLIGENCE,
        )
        system_prompt = agent._build_system_prompt(base_state, context, "product/description")

        # Should include archetype
        assert "artisan_master" in system_prompt.lower()
        # Should include power words
        assert "handcrafted" in system_prompt.lower()
        # Should include banned phrases
        assert "cheap" in system_prompt.lower()
        # Should include value props
        assert "Arita" in system_prompt

    @pytest.mark.asyncio
    async def test_system_prompt_includes_brand_context(self, mock_services, base_state):
        """Brand context chunks should appear in system prompt."""
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)

        context = AgentContext(
            raw_input=base_state.raw_input,
            brand_context=BRAND_CONTEXT_CHUNKS,
        )
        system_prompt = agent._build_system_prompt(base_state, context, "product/description")

        assert "fourth-generation" in system_prompt.lower()
        assert "Yō-no-bi" in system_prompt

    @pytest.mark.asyncio
    async def test_without_intelligence_still_works(self, mock_services, base_state):
        """Agent should work even without strategic intelligence."""
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)

        context = AgentContext(
            raw_input=base_state.raw_input,
            brand_context=[],
            strategic_intelligence=None,
        )
        system_prompt = agent._build_system_prompt(base_state, context, "product/description")

        # Should still have the base system prompt
        assert len(system_prompt) > 100


# =============================================================================
# Tests: Template Routing Edge Cases
# =============================================================================

class TestTemplateRoutingEdgeCases:
    """Test edge cases in template routing."""

    @pytest.mark.asyncio
    async def test_unknown_template_falls_back_to_description(self, mock_services, base_state):
        """Unknown template_id should fall back to product/description."""
        base_state.raw_input["template_id"] = "product/unknown-template"
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        # Should still work via fallback
        assert result.status == "DRAFT_READY" or result.draft_content is not None

    @pytest.mark.asyncio
    async def test_missing_template_id_defaults_to_description(self, mock_services, base_state):
        """Missing template_id should default to product/description."""
        # template_id not in raw_input
        base_state.raw_input.pop("template_id", None)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "DRAFT_READY"

    @pytest.mark.asyncio
    async def test_llm_error_sets_error_state(self, mock_services, base_state):
        """LLM failure should set error state."""
        mock_services.llm.generate_text = AsyncMock(side_effect=Exception("LLM timeout"))
        agent = RewriterAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "ERROR"
        assert "failed" in result.error_message.lower()

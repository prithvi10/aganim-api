"""
Integration Tests: RewriterAgent End-to-End with Brand Soul.

Simulates the complete pipeline:
1. Brand soul text → IntelligenceExtractor → Strategic Audit JSON
2. Brand soul text → RAG chunks with entity metadata
3. RewriterAgent perceive (loads brand context + strategic intelligence)
4. RewriterAgent act (generates content using template with operational rules)
5. Validates output against brand voice rules

Uses MOCKED LLM responses (no live OpenAI calls) but exercises the full
orchestration layer, prompt construction, parsing, and state management.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from src.main.agents.rewriter import RewriterAgent
from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext

from src.test.fixtures.brand_soul_fixtures import (
    BRAND_SOUL_RAW_TEXT,
    STRATEGIC_INTELLIGENCE,
    BRAND_CONTEXT_CHUNKS,
    PRODUCT_CELADON_BOWL,
    PRODUCT_TEAPOT,
    PRODUCT_VASE,
    MOCK_PRODUCT_DESCRIPTION_RESPONSE,
    MOCK_PRODUCT_TITLE_RESPONSE,
    MOCK_COLLECTION_RESPONSE,
    MOCK_FAQ_RESPONSE,
    MOCK_LANDING_HERO_RESPONSE,
    BRAND_VOICE_MUST_INCLUDE_KEYWORDS,
    BRAND_VOICE_BANNED_WORDS,
)


# =============================================================================
# Helpers
# =============================================================================

def _assert_brand_voice(text: str, min_keywords: int = 2):
    """Assert brand voice compliance."""
    text_lower = text.lower()
    matches = [kw for kw in BRAND_VOICE_MUST_INCLUDE_KEYWORDS if kw.lower() in text_lower]
    assert len(matches) >= min_keywords, (
        f"Expected at least {min_keywords} brand keywords, found {len(matches)}: {matches}"
    )
    for banned in BRAND_VOICE_BANNED_WORDS:
        assert banned.lower() not in text_lower, f"Banned word '{banned}' in output"


def _create_mock_services(llm_response: str):
    """Create mock services with a specific LLM response."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value=llm_response)
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=BRAND_CONTEXT_CHUNKS)
    services.rag._get_strategic_intelligence = AsyncMock(return_value=STRATEGIC_INTELLIGENCE)
    return services


# =============================================================================
# Integration: Full Pipeline — Product Description
# =============================================================================

class TestRewriterDescriptionE2E:
    """End-to-end tests for the product description pipeline."""

    @pytest.mark.asyncio
    async def test_celadon_bowl_full_pipeline(self):
        """Complete pipeline: brand soul → context → description for celadon bowl."""
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
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

        result = await agent.run(state)

        # Pipeline completed
        assert result.status == "DRAFT_READY"
        # Content generated
        assert result.draft_content is not None
        assert len(result.draft_content) > 100
        # Title extracted
        assert result.draft_title is not None
        assert "Celadon" in result.draft_title
        # Discovered values
        assert len(result.discovered_values) >= 1
        # Brand voice
        _assert_brand_voice(result.draft_content)

    @pytest.mark.asyncio
    async def test_teapot_full_pipeline(self):
        """Complete pipeline for the Gosu Blue Teapot product."""
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_TEAPOT["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": PRODUCT_TEAPOT["title"],
                "description": PRODUCT_TEAPOT["description"],
                "category": PRODUCT_TEAPOT["category"],
                "target_locale": "en",
            },
            target_locale="en",
        )

        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_vase_full_pipeline(self):
        """Complete pipeline for the Noborigama Ash Glaze Vase."""
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_VASE["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_VASE["title"],
                "description": PRODUCT_VASE["description"],
                "category": PRODUCT_VASE["category"],
                "target_locale": "en",
            },
            target_locale="en",
        )

        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None


# =============================================================================
# Integration: Full Pipeline — All Templates
# =============================================================================

class TestRewriterAllTemplatesE2E:
    """End-to-end tests for every rewriter template."""

    @pytest.mark.asyncio
    async def test_title_template_e2e(self):
        """Title generation pipeline."""
        services = _create_mock_services(MOCK_PRODUCT_TITLE_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "product/title",
            },
            target_locale="en",
        )

        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_title is not None
        assert "Celadon" in result.draft_title

        # Verify the LLM was called with title-specific prompt
        call_kwargs = services.llm.generate_text.call_args.kwargs
        system_prompt = call_kwargs.get("system_prompt", "")
        assert "70 character" in system_prompt.lower()

    @pytest.mark.asyncio
    async def test_collection_template_e2e(self):
        """Collection description pipeline."""
        services = _create_mock_services(MOCK_COLLECTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "product/collection",
                "collection_name": "Heritage Celadon Collection",
                "products": "Rice Bowl, Sake Cup, Side Plate",
            },
            target_locale="en",
        )

        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None
        _assert_brand_voice(result.draft_content)

        # Verify collection name was in the prompt
        call_kwargs = services.llm.generate_text.call_args.kwargs
        assert "Heritage Celadon Collection" in call_kwargs.get("prompt", "")

    @pytest.mark.asyncio
    async def test_faq_template_e2e(self):
        """FAQ generation pipeline."""
        services = _create_mock_services(MOCK_FAQ_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "product/faq",
            },
            target_locale="en",
        )

        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

        # Verify FAQ content
        parsed = json.loads(MOCK_FAQ_RESPONSE)
        all_answers = " ".join(faq["answer"] for faq in parsed["faqs"])
        _assert_brand_voice(all_answers)

    @pytest.mark.asyncio
    async def test_landing_hero_template_e2e(self):
        """Landing page hero generation pipeline."""
        services = _create_mock_services(MOCK_LANDING_HERO_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": "product/landing-hero",
            },
            target_locale="en",
        )

        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

        # Verify hero content
        parsed = json.loads(MOCK_LANDING_HERO_RESPONSE)
        all_text = f"{parsed['headline']} {parsed['subheadline']} {parsed['hero_description']}"
        _assert_brand_voice(all_text)


# =============================================================================
# Integration: Prompt Construction with Full Context
# =============================================================================

class TestPromptConstructionE2E:
    """Verify the system prompt has all expected layers."""

    @pytest.mark.asyncio
    async def test_description_prompt_has_all_layers(self):
        """System prompt should include operational rules + base prompt + tone + brand context."""
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        # Manually build context with all data
        context = AgentContext(
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
            },
            brand_context=BRAND_CONTEXT_CHUNKS,
            strategic_intelligence=STRATEGIC_INTELLIGENCE,
        )

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "tone": "professional",
                "target_locale": "en",
            },
            target_locale="en",
        )

        prompt = agent._build_system_prompt(state, context, "product/description")

        # Layer 1: Operational rules (from strategic intelligence)
        assert "OPERATIONAL RULES" in prompt
        assert "artisan_master" in prompt.lower()
        assert "handcrafted" in prompt.lower()
        assert "cheap" in prompt.lower()

        # Layer 2: Base system prompt
        assert len(prompt) > 500  # Should be substantial

        # Layer 3: Brand context
        assert "fourth-generation" in prompt.lower()
        assert "Yō-no-bi" in prompt

    @pytest.mark.asyncio
    async def test_title_prompt_uses_template_system_prompt(self):
        """Title template should inject its specific system prompt."""
        services = _create_mock_services(MOCK_PRODUCT_TITLE_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        context = AgentContext(
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": "Tableware",
            },
            strategic_intelligence=STRATEGIC_INTELLIGENCE,
        )

        state = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": "Tableware",
                "target_locale": "en",
            },
            target_locale="en",
        )

        prompt = agent._build_system_prompt(state, context, "product/title")

        # Should have title-specific prompt
        assert "70 character" in prompt.lower()
        assert "seo" in prompt.lower()
        # And still have operational rules
        assert "OPERATIONAL RULES" in prompt


# =============================================================================
# Integration: State Flow Validation
# =============================================================================

class TestStateFlowE2E:
    """Verify the state is correctly updated through the pipeline."""

    @pytest.mark.asyncio
    async def test_state_transitions(self):
        """State should transition: PENDING → (internal) → DRAFT_READY."""
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
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

        assert state.status == "PENDING"
        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

    @pytest.mark.asyncio
    async def test_audit_trail(self):
        """Logs should record perceive → plan → execute → complete."""
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
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

        result = await agent.run(state)

        assert any("Perceiving" in log for log in result.logs)
        assert any("Planning" in log for log in result.logs)
        assert any("Executing" in log for log in result.logs)
        assert any("Completed" in log for log in result.logs)

    @pytest.mark.asyncio
    async def test_state_serializable(self):
        """Result state should be JSON-serializable."""
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
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

        result = await agent.run(state)
        state_dict = result.to_dict()

        # Should be serializable to JSON
        serialized = json.dumps(state_dict, ensure_ascii=False)
        assert len(serialized) > 100

        # Should contain key fields
        deserialized = json.loads(serialized)
        assert deserialized["status"] == "DRAFT_READY"
        assert deserialized["draft_content"] is not None


# =============================================================================
# Integration: Multi-Product Consistency
# =============================================================================

class TestMultiProductConsistency:
    """Test that brand voice is consistent across different products."""

    @pytest.mark.asyncio
    async def test_all_three_products_draft_ready(self):
        """All three products should produce DRAFT_READY status."""
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        products = [PRODUCT_CELADON_BOWL, PRODUCT_TEAPOT, PRODUCT_VASE]

        for product in products:
            state = MissionState(
                product_id=product["id"],
                shop_id="takumi-ceramics.myshopify.com",
                plan_tier="Pro",
                raw_input={
                    "title": product["title"],
                    "description": product["description"],
                    "category": product["category"],
                    "target_locale": "en",
                },
                target_locale="en",
            )

            result = await agent.run(state)
            assert result.status == "DRAFT_READY", (
                f"Product {product['title']} failed: {result.error_message}"
            )

    @pytest.mark.asyncio
    async def test_all_templates_for_celadon_bowl(self):
        """All 5 templates should produce valid output for the same product."""
        template_responses = {
            "product/description": MOCK_PRODUCT_DESCRIPTION_RESPONSE,
            "product/title": MOCK_PRODUCT_TITLE_RESPONSE,
            "product/collection": MOCK_COLLECTION_RESPONSE,
            "product/faq": MOCK_FAQ_RESPONSE,
            "product/landing-hero": MOCK_LANDING_HERO_RESPONSE,
        }

        for template_id, mock_response in template_responses.items():
            services = _create_mock_services(mock_response)
            agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

            raw_input = {
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "template_id": template_id,
            }
            # Add extra fields for collection template
            if template_id == "product/collection":
                raw_input["collection_name"] = "Celadon Jade Collection"
                raw_input["products"] = "Rice Bowl, Sake Cup"

            state = MissionState(
                product_id=PRODUCT_CELADON_BOWL["id"],
                shop_id="takumi-ceramics.myshopify.com",
                plan_tier="Pro",
                raw_input=raw_input,
                target_locale="en",
            )

            result = await agent.run(state)
            assert result.status == "DRAFT_READY", (
                f"Template {template_id} failed: {result.error_message}"
            )


# =============================================================================
# Integration: Refinement Mode
# =============================================================================

class TestRefinementModeE2E:
    """Test the refinement/regeneration flow."""

    @pytest.mark.asyncio
    async def test_refinement_with_previous_draft(self):
        """Agent should refine existing draft when feedback is provided."""
        # First run: generate initial draft
        services = _create_mock_services(MOCK_PRODUCT_DESCRIPTION_RESPONSE)
        agent = RewriterAgent("takumi-ceramics.myshopify.com", services)

        state = MissionState(
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

        first_result = await agent.run(state)
        assert first_result.status == "DRAFT_READY"

        # Second run: refinement with feedback
        refinement_response = MOCK_PRODUCT_DESCRIPTION_RESPONSE  # Reuse for simplicity
        services2 = _create_mock_services(refinement_response)
        agent2 = RewriterAgent("takumi-ceramics.myshopify.com", services2)

        state2 = MissionState(
            product_id=PRODUCT_CELADON_BOWL["id"],
            shop_id="takumi-ceramics.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": PRODUCT_CELADON_BOWL["category"],
                "target_locale": "en",
                "_regeneration_feedback": "Make the introduction more poetic, emphasize the jade whisper finish.",
            },
            target_locale="en",
            draft_content=first_result.draft_content,
            draft_title=first_result.draft_title,
        )

        refined_result = await agent2.run(state2)
        assert refined_result.status == "DRAFT_READY"

        # Should have called LLM with refinement prompt
        call_kwargs = services2.llm.generate_text.call_args.kwargs
        assert call_kwargs.get("temperature") == 0.5  # Lower temp for refinement

"""
Unit tests for ContentHeroAgent -- Hero image generation for blog/collection content.

Uses HeroImageGenerator (Nano Banana text-to-image) instead of VisualService.expand_hero.

Covers:
  - _perceive_domain: context extraction from agent_outputs for blog/collection/hero
  - _act_domain: happy path, no preceding content skip, error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.content_hero.agent import ContentHeroAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan

_HERO_GEN = "src.ecommerce.services.hero_image_generator.HeroImageGenerator"
_R2_SVC = "src.ecommerce.services.r2_storage_service.R2StorageService"

FAKE_IMAGE_BYTES = b"fake-hero-image-bytes"


@pytest.fixture
def mock_services():
    services = MagicMock()
    services.rag.get_brand_context = AsyncMock(return_value=[])
    services.rag.get_strategic_intelligence = AsyncMock(return_value=None)
    return services


@pytest.fixture
def agent(mock_services):
    return ContentHeroAgent("test-shop.myshopify.com", services=mock_services)


@pytest.fixture
def default_plan():
    return AgentPlan(
        steps=["generate_hero"],
        selected_tools=["content_hero.generate"],
        confidence=1.0,
        reasoning="Content hero pipeline",
    )


class TestContentHeroAgentAttributes:
    def test_role_name(self):
        assert ContentHeroAgent.role_name == "ContentHero"

    def test_requires_no_llm(self):
        assert ContentHeroAgent.requires_llm_reasoning is False

    def test_default_tool(self):
        assert ContentHeroAgent.default_tool == "content_hero.generate"


class TestPerceiveDomain:
    @pytest.mark.asyncio
    async def test_extracts_blog_context(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"topic": "Japanese ceramics", "category": "Artisan"},
        )
        state.agent_outputs = {
            "RewriterAgent_0": {
                "template_id": "product/blog-post",
                "draft_title": "The Art of Japanese Ceramics",
                "draft_content": "...",
            }
        }
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)

        assert ctx.external_data["template_id"] == "product/blog-post"
        assert ctx.external_data["context_data"]["subject"] == "The Art of Japanese Ceramics"
        assert ctx.external_data["context_data"]["category"] == "Artisan"

    @pytest.mark.asyncio
    async def test_extracts_collection_context(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={
                "collection_name": "Summer Collection",
                "description": "Our best summer picks",
                "product_names": ["Sake A", "Sake B"],
            },
        )
        state.agent_outputs = {
            "RewriterAgent_0": {
                "template_id": "product/collection",
                "draft_content": "...",
            }
        }
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)

        assert ctx.external_data["template_id"] == "product/collection"
        assert ctx.external_data["context_data"]["collection_name"] == "Summer Collection"
        assert ctx.external_data["context_data"]["description"] == "Our best summer picks"
        assert ctx.external_data["context_data"]["product_names"] == ["Sake A", "Sake B"]

    @pytest.mark.asyncio
    async def test_extracts_landing_hero_context(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"subject_text": "Spring Flowers"},
        )
        state.agent_outputs = {
            "RewriterAgent_0": {
                "template_id": "product/landing-hero",
                "draft_title": "Elevate Your Space",
            }
        }
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)

        assert ctx.external_data["template_id"] == "product/landing-hero"
        assert ctx.external_data["context_data"]["subject"] == "Elevate Your Space"

    @pytest.mark.asyncio
    async def test_no_preceding_content(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)

        assert ctx.external_data["template_id"] == ""
        assert ctx.external_data["context_data"] == {}

    @pytest.mark.asyncio
    async def test_brand_soul_from_strategic_intelligence(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={},
        )
        state.agent_outputs = {}
        ctx = AgentContext(
            raw_input=state.raw_input,
            strategic_intelligence={"archetype": "Artisan", "tone": "refined"},
        )
        ctx = await agent._perceive_domain(state, ctx)
        assert len(ctx.external_data["brand_soul"]) > 0
        assert len(ctx.external_data["brand_soul"]) <= 300

    @pytest.mark.asyncio
    async def test_collection_product_names_as_csv_string(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={
                "collection_name": "Premium",
                "product_names": "Sake A, Sake B, Sake C",
            },
        )
        state.agent_outputs = {
            "RewriterAgent_0": {"template_id": "product/collection"}
        }
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)
        assert ctx.external_data["context_data"]["product_names"] == ["Sake A", "Sake B", "Sake C"]


class TestActDomainHappyPath:
    @pytest.mark.asyncio
    async def test_blog_hero_generation(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"topic": "Japanese ceramics"},
        )

        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "template_id": "product/blog-post",
                "context_data": {
                    "subject": "The Art of Japanese Ceramics",
                    "category": "Artisan",
                    "context": "",
                },
                "brand_soul": "Minimalist Kyoto",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://content-hero.png")

        with patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        mock_hero_gen.generate.assert_called_once()
        call_kwargs = mock_hero_gen.generate.call_args
        assert "blog" in call_kwargs.kwargs.get("prompt", call_kwargs.args[0] if call_kwargs.args else "").lower() or \
               "blog" in str(call_kwargs).lower()

        assert len(actions) == 1
        assert actions[0].success is True

        assert new_state.content_hero_assets is not None
        assert new_state.content_hero_assets["hero_url"] == "r2://content-hero.png"
        assert new_state.content_hero_assets["content_type"] == "blog"

    @pytest.mark.asyncio
    async def test_collection_hero_generation(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"collection_name": "Summer Sake"},
        )

        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "template_id": "product/collection",
                "context_data": {
                    "collection_name": "Summer Sake",
                    "description": "Our best summer picks",
                    "product_names": ["Yuzu Sake", "Plum Sake"],
                },
                "brand_soul": "",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://collection-hero.png")

        with patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        assert actions[0].success is True
        assert new_state.content_hero_assets["content_type"] == "collection"
        assert new_state.content_hero_assets["theme_context"] == "Summer Sake"


class TestActDomainSkips:
    @pytest.mark.asyncio
    async def test_no_preceding_content_skips(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={},
        )
        context = AgentContext(
            raw_input={},
            external_data={
                "template_id": "",
                "context_data": {},
                "brand_soul": "",
            },
        )

        actions, _ = await agent._act_domain(state, context, default_plan)

        assert len(actions) == 1
        assert actions[0].success is False
        assert "no_preceding_content" in str(actions[0].input_params)


class TestActDomainFailure:
    @pytest.mark.asyncio
    async def test_hero_gen_fails(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )
        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "template_id": "product/blog-post",
                "context_data": {"subject": "Test", "category": "General", "context": ""},
                "brand_soul": "",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(
            side_effect=TimeoutError("fal.ai timeout")
        )

        with patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC):
            actions, new_state = await agent._act_domain(state, context, default_plan)

        assert actions[0].success is False
        assert "fal.ai timeout" in actions[0].error
        assert new_state.visual_progress["phase"] == "error"

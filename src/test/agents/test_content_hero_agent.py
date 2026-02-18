"""
Unit tests for ContentHeroAgent -- Hero image generation for blog/collection content.

Covers:
  - _perceive_domain: context extraction from agent_outputs for blog/collection/hero
  - _act_domain: happy path, no image skip, no preceding content skip, error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.content_hero.agent import ContentHeroAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan

_VISUAL_SVC = "src.ecommerce.services.visual_service.VisualService"
_R2_SVC = "src.ecommerce.services.r2_storage_service.R2StorageService"
_HTTPX_ASYNC_CLIENT = "httpx.AsyncClient"

FAKE_IMAGE_BYTES = b"fake-hero-image-bytes"


def _make_httpx_mock(response_content=FAKE_IMAGE_BYTES):
    mock_response = MagicMock()
    mock_response.content = response_content
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


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
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg", "topic": "Japanese ceramics"},
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

        assert ctx.external_data["subject"] == "Blog"
        assert ctx.external_data["context_text"] == "The Art of Japanese Ceramics"
        assert ctx.external_data["image_url"] == "https://cdn.shopify.com/p.jpg"

    @pytest.mark.asyncio
    async def test_extracts_collection_context(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={
                "image_url": "https://cdn.shopify.com/p.jpg",
                "collection_name": "Summer Collection",
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

        assert ctx.external_data["subject"] == "Collection"
        assert ctx.external_data["context_text"] == "Summer Collection"

    @pytest.mark.asyncio
    async def test_extracts_landing_hero_context(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg", "title": "Featured"},
        )
        state.agent_outputs = {
            "RewriterAgent_0": {
                "template_id": "product/landing-hero",
                "draft_title": "Elevate Your Space",
            }
        }
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)

        assert ctx.external_data["subject"] == "Hero section"
        assert ctx.external_data["context_text"] == "Elevate Your Space"

    @pytest.mark.asyncio
    async def test_no_preceding_content(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg"},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)

        assert ctx.external_data["subject"] == ""
        assert ctx.external_data["context_text"] == ""

    @pytest.mark.asyncio
    async def test_brand_soul_from_strategic_intelligence(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg"},
        )
        state.agent_outputs = {}
        ctx = AgentContext(
            raw_input=state.raw_input,
            strategic_intelligence={"archetype": "Artisan", "tone": "refined"},
        )
        ctx = await agent._perceive_domain(state, ctx)
        assert len(ctx.external_data["short_soul"]) > 0
        assert len(ctx.external_data["short_soul"]) <= 120


class TestActDomainHappyPath:
    @pytest.mark.asyncio
    async def test_blog_hero_generation(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg", "topic": "Japanese ceramics"},
        )
        state.agent_outputs = {
            "RewriterAgent_0": {
                "template_id": "product/blog-post",
                "draft_title": "The Art of Japanese Ceramics",
            }
        }

        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/p.jpg",
                "subject": "Blog",
                "context_text": "The Art of Japanese Ceramics",
                "short_soul": "Minimalist Kyoto",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.expand_hero = AsyncMock(return_value="https://fal.ai/hero.png")

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://content-hero.png")
        mock_client = _make_httpx_mock()

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client):

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")

            actions, new_state = await agent._act_domain(state, context, default_plan)

        mock_visual_svc.expand_hero.assert_called_once()
        assert mock_r2_svc.upload_asset.call_count == 1

        assert len(actions) == 1
        assert actions[0].success is True

        assert new_state.content_hero_assets is not None
        assert new_state.content_hero_assets["hero_url"] == "r2://content-hero.png"
        assert new_state.content_hero_assets["content_type"] == "blog"
        assert new_state.content_hero_assets["theme_context"] == "The Art of Japanese Ceramics"


class TestActDomainSkips:
    @pytest.mark.asyncio
    async def test_no_image_url_skips(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={},
        )
        context = AgentContext(
            raw_input={},
            external_data={
                "image_url": "",
                "subject": "Blog",
                "context_text": "Some topic",
                "short_soul": "",
            },
        )

        actions, _ = await agent._act_domain(state, context, default_plan)

        assert len(actions) == 1
        assert actions[0].success is False
        assert "no_image_url" in str(actions[0].input_params)

    @pytest.mark.asyncio
    async def test_no_preceding_content_skips(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg"},
        )
        context = AgentContext(
            raw_input={},
            external_data={
                "image_url": "https://cdn.shopify.com/p.jpg",
                "subject": "",
                "context_text": "",
                "short_soul": "",
            },
        )

        actions, _ = await agent._act_domain(state, context, default_plan)

        assert len(actions) == 1
        assert actions[0].success is False
        assert "no_preceding_content" in str(actions[0].input_params)


class TestActDomainFailure:
    @pytest.mark.asyncio
    async def test_expand_hero_fails(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg"},
        )
        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/p.jpg",
                "subject": "Blog",
                "context_text": "Test",
                "short_soul": "",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.expand_hero = AsyncMock(
            side_effect=TimeoutError("fal.ai timeout")
        )

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC):
            actions, new_state = await agent._act_domain(state, context, default_plan)

        assert actions[0].success is False
        assert "fal.ai timeout" in actions[0].error
        assert new_state.visual_progress["phase"] == "error"

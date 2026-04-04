"""
Unit tests for ContentHeroAgent -- Art-directed hero image generation.

Covers:
  - _perceive_domain: context extraction from agent_outputs for blog/collection/hero,
    plus new fields: image_style, image_url, brand_name, product_name, product_category
  - _act_domain: happy path with Art Director + style routing, img2img path,
    seasonal detection, informative logo, no preceding content skip, error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.content_hero.agent import ContentHeroAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan
from src.ecommerce.services.art_director import VisualBrief

_HERO_GEN = "src.ecommerce.services.hero_image_generator.HeroImageGenerator"
_R2_SVC = "src.ecommerce.services.r2_storage_service.R2StorageService"
_ART_DIRECTOR = "src.ecommerce.services.art_director.generate_visual_brief"
_BUILD_STYLED = "src.ecommerce.agents.visual.prompts.build_styled_prompt"

FAKE_IMAGE_BYTES = b"fake-hero-image-bytes"

MOCK_BRIEF = VisualBrief(
    surface_material="polished marble",
    environment="soft studio backdrop",
    lighting_scheme="diffused natural light",
    color_palette=["ivory", "grey", "gold"],
    suggested_props="coffee beans, cinnamon sticks",
)


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
    async def test_extracts_short_description_for_landing_hero(self, agent):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"subject_text": "Spring Flowers", "short_description": "Fresh seasonal blooms"},
        )
        state.agent_outputs = {
            "RewriterAgent_0": {
                "template_id": "product/landing-hero",
                "draft_title": "Spring Flowers",
            }
        }
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)

        assert ctx.external_data["context_data"]["short_description"] == "Fresh seasonal blooms"

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
            raw_input={"brand_soul_enabled": True},
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

    @pytest.mark.asyncio
    async def test_extracts_image_style(self, agent):
        state = MissionState(
            product_id="p1", shop_id="s1", plan_tier="Pro",
            raw_input={"image_style": "seasonal"},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)
        assert ctx.external_data["image_style"] == "seasonal"

    @pytest.mark.asyncio
    async def test_default_image_style_is_attractive(self, agent):
        state = MissionState(
            product_id="p1", shop_id="s1", plan_tier="Pro",
            raw_input={},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)
        assert ctx.external_data["image_style"] == "attractive"

    @pytest.mark.asyncio
    async def test_extracts_image_url(self, agent):
        state = MissionState(
            product_id="p1", shop_id="s1", plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/product.jpg"},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)
        assert ctx.external_data["image_url"] == "https://cdn.shopify.com/product.jpg"

    @pytest.mark.asyncio
    async def test_extracts_brand_name(self, agent):
        state = MissionState(
            product_id="p1", shop_id="s1", plan_tier="Pro",
            raw_input={"brand_name": "Kyoto Artisan"},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)
        assert ctx.external_data["brand_name"] == "Kyoto Artisan"

    @pytest.mark.asyncio
    async def test_extracts_product_name(self, agent):
        state = MissionState(
            product_id="p1", shop_id="s1", plan_tier="Pro",
            raw_input={"product_name": "Premium Matcha"},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)
        assert ctx.external_data["product_name"] == "Premium Matcha"

    @pytest.mark.asyncio
    async def test_extracts_product_category(self, agent):
        state = MissionState(
            product_id="p1", shop_id="s1", plan_tier="Pro",
            raw_input={"category": "Beverage"},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)
        assert ctx.external_data["product_category"] == "Beverage"

    @pytest.mark.asyncio
    async def test_default_product_category_is_general(self, agent):
        state = MissionState(
            product_id="p1", shop_id="s1", plan_tier="Pro",
            raw_input={},
        )
        state.agent_outputs = {}
        ctx = AgentContext(raw_input=state.raw_input)
        ctx = await agent._perceive_domain(state, ctx)
        assert ctx.external_data["product_category"] == "General"


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
                "image_style": "attractive",
                "image_url": "",
                "brand_name": "",
                "product_name": "The Art of Japanese Ceramics",
                "product_category": "Artisan",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://content-hero.png")

        with patch(_ART_DIRECTOR, new=AsyncMock(return_value=MOCK_BRIEF)), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        mock_hero_gen.generate.assert_called_once()

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
                "image_style": "attractive",
                "image_url": "",
                "brand_name": "",
                "product_name": "Summer Sake",
                "product_category": "General",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://collection-hero.png")

        with patch(_ART_DIRECTOR, new=AsyncMock(return_value=MOCK_BRIEF)), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        assert actions[0].success is True
        assert new_state.content_hero_assets["content_type"] == "collection"
        assert new_state.content_hero_assets["theme_context"] == "Summer Sake"

    @pytest.mark.asyncio
    async def test_attractive_style_calls_art_director(self, agent, default_plan):
        """Verify Art Director is called and build_styled_prompt is used."""
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
                "context_data": {"subject": "Coffee Guide", "category": "Beverage", "context": ""},
                "brand_soul": "",
                "image_style": "attractive",
                "image_url": "",
                "brand_name": "",
                "product_name": "Coffee Guide",
                "product_category": "Beverage",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://hero.png")
        mock_art_director = AsyncMock(return_value=MOCK_BRIEF)

        with patch(_ART_DIRECTOR, new=mock_art_director), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        mock_art_director.assert_called_once()
        assert actions[0].success is True
        assert new_state.content_hero_assets["image_style"] == "attractive"

    @pytest.mark.asyncio
    async def test_img2img_generation(self, agent, default_plan):
        """When image_url is set, generate_from_image should be called instead of generate."""
        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )
        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "template_id": "product/landing-hero",
                "context_data": {"subject": "Spring Flowers", "short_description": ""},
                "brand_soul": "",
                "image_style": "attractive",
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_name": "",
                "product_name": "Spring Flowers",
                "product_category": "General",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_hero_gen.generate_from_image = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://hero.png")

        with patch(_ART_DIRECTOR, new=AsyncMock(return_value=MOCK_BRIEF)), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        mock_hero_gen.generate_from_image.assert_called_once()
        mock_hero_gen.generate.assert_not_called()
        assert actions[0].success is True
        assert actions[0].input_params["has_product_image"] is True

    @pytest.mark.asyncio
    async def test_seasonal_style_with_season(self, agent, default_plan):
        """Seasonal style should trigger season detection."""
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
                "context_data": {"subject": "Holiday Guide", "category": "Seasonal", "context": ""},
                "brand_soul": "",
                "image_style": "seasonal",
                "image_url": "",
                "brand_name": "",
                "product_name": "Holiday Guide",
                "product_category": "Seasonal",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://hero.png")
        styled_prompt_spy = MagicMock(return_value="styled prompt result")

        with patch(_ART_DIRECTOR, new=AsyncMock(return_value=MOCK_BRIEF)), \
             patch(_BUILD_STYLED, new=styled_prompt_spy), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        styled_prompt_spy.assert_called_once()
        call_kwargs = styled_prompt_spy.call_args.kwargs
        assert call_kwargs["style"] == "seasonal"
        assert len(call_kwargs["season"]) > 0
        assert len(call_kwargs["season_props"]) > 0
        assert actions[0].success is True

    @pytest.mark.asyncio
    async def test_informative_style_with_logo(self, agent, default_plan):
        """Informative style with brand_name passes it to build_styled_prompt."""
        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )
        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "template_id": "product/landing-hero",
                "context_data": {"subject": "Premium Matcha", "short_description": ""},
                "brand_soul": "",
                "image_style": "informative",
                "image_url": "",
                "brand_name": "Kyoto Brews",
                "product_name": "Premium Matcha",
                "product_category": "Beverage",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://hero.png")
        styled_prompt_spy = MagicMock(return_value="styled prompt with logo")

        with patch(_ART_DIRECTOR, new=AsyncMock(return_value=MOCK_BRIEF)), \
             patch(_BUILD_STYLED, new=styled_prompt_spy), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        styled_prompt_spy.assert_called_once()
        call_kwargs = styled_prompt_spy.call_args.kwargs
        assert call_kwargs["style"] == "informative"
        assert call_kwargs["brand_name"] == "Kyoto Brews"
        assert actions[0].success is True


class TestImageCreditDeduction:
    """Verify image credit usage tracking fires after successful hero generation."""

    @pytest.mark.asyncio
    async def test_image_credit_recorded_on_success(self, agent, default_plan):
        mock_db = MagicMock()
        mock_shop_record = MagicMock()
        mock_shop_record.monthly_image_generations_used = 5
        mock_db.query.return_value.filter.return_value.first.return_value = mock_shop_record

        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"topic": "Japanese ceramics"},
        )
        state.db = mock_db

        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "template_id": "product/blog-post",
                "context_data": {"subject": "Ceramics", "category": "Artisan", "context": ""},
                "brand_soul": "",
                "image_style": "attractive",
                "image_url": "",
                "brand_name": "",
                "product_name": "Ceramics",
                "product_category": "Artisan",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://hero.png")

        with patch(_ART_DIRECTOR, new=AsyncMock(return_value=MOCK_BRIEF)), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch("src.ecommerce.db.transactions.record_feature_usage") as mock_record, \
             patch("src.ecommerce.db.transactions.log_usage_event") as mock_log, \
             patch("src.ecommerce.db.transactions.check_image_quota"), \
             patch("src.ecommerce.plans.entitlements.get_entitlements", return_value={"image_limit_type": "monthly"}):
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        assert actions[0].success is True
        mock_record.assert_called_once_with(mock_db, "test-shop.myshopify.com", "image_generation", 1)
        mock_log.assert_called_once()
        log_kwargs = mock_log.call_args
        assert log_kwargs[1]["event_type"] == "content_hero"
        assert log_kwargs[1]["feature"] == "image_generation"
        assert log_kwargs[1]["agent_name"] == "ContentHeroAgent"

    @pytest.mark.asyncio
    async def test_credit_deduction_failure_does_not_break_generation(self, agent, default_plan):
        """If credit tracking throws, the hero image should still succeed."""
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("DB error")

        state = MissionState(
            product_id="p1",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )
        state.db = mock_db

        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "template_id": "product/blog-post",
                "context_data": {"subject": "Test", "category": "General", "context": ""},
                "brand_soul": "",
                "image_style": "attractive",
                "image_url": "",
                "brand_name": "",
                "product_name": "Test",
                "product_category": "General",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://hero.png")

        with patch(_ART_DIRECTOR, new=AsyncMock(return_value=MOCK_BRIEF)), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC) as mock_r2_cls:
            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")
            actions, new_state = await agent._act_domain(state, context, default_plan)

        assert actions[0].success is True
        assert new_state.content_hero_assets is not None


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
                "image_style": "attractive",
                "image_url": "",
                "brand_name": "",
                "product_name": "Test",
                "product_category": "General",
            },
        )

        mock_hero_gen = MagicMock()
        mock_hero_gen.generate = AsyncMock(
            side_effect=TimeoutError("fal.ai timeout")
        )

        with patch(_ART_DIRECTOR, new=AsyncMock(return_value=MOCK_BRIEF)), \
             patch(_HERO_GEN, return_value=mock_hero_gen), \
             patch(_R2_SVC):
            actions, new_state = await agent._act_domain(state, context, default_plan)

        assert actions[0].success is False
        assert "fal.ai timeout" in actions[0].error
        assert new_state.visual_progress["phase"] == "error"

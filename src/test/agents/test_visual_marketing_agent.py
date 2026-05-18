"""
Unit tests for VisualMarketingAgent -- Marketing ad generation via Nano Banana.

Covers:
  - _perceive_domain: context extraction for refined image, hooks, brand soul
  - _act_domain: Nano Banana pipeline (ProductAdGenerator), no-image skip,
    error handling, brand_style disabled by default
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.visual_marketing.agent import VisualMarketingAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan

_R2_SVC = "src.ecommerce.services.r2_storage_service.R2StorageService"
_AD_GEN = "src.ecommerce.services.product_ad_generator.ProductAdGenerator"

FAKE_AD_BYTES = b"fake-ad-png-bytes"


@pytest.fixture
def mock_services():
    services = MagicMock()
    services.rag.get_brand_context = AsyncMock(return_value=[])
    return services


@pytest.fixture
def agent(mock_services):
    return VisualMarketingAgent("test-shop.myshopify.com", services=mock_services)


@pytest.fixture
def pro_state():
    state = MissionState(
        product_id="product-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "product_name": "Handcrafted Ceramic Bowl",
            "image_url": "https://cdn.shopify.com/product.jpg",
            "brand_name": "Kyoto Artisan",
            "hook_text": "New Collection",
        },
    )
    state.visual_assets = {
        "refined_url": "https://cdn.shopify.com/refined.png",
        "original_image_url": "https://cdn.shopify.com/product.jpg",
    }
    return state


@pytest.fixture
def context_base():
    return AgentContext(
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "product_name": "Handcrafted Ceramic Bowl",
            "image_url": "https://cdn.shopify.com/product.jpg",
        },
    )


@pytest.fixture
def default_plan():
    return AgentPlan(
        steps=["generate_marketing"],
        selected_tools=["visual_marketing.generate"],
        confidence=1.0,
        reasoning="Visual marketing pipeline",
    )


class TestVisualMarketingAgentAttributes:
    def test_role_name(self):
        assert VisualMarketingAgent.role_name == "VisualMarketing"

    def test_requires_no_llm(self):
        assert VisualMarketingAgent.requires_llm_reasoning is False

    def test_default_tool(self):
        assert VisualMarketingAgent.default_tool == "visual_marketing.generate"


class TestPerceiveDomain:
    @pytest.mark.asyncio
    async def test_prefers_refined_url(self, agent, pro_state, context_base):
        """Should use refined_url from visual_assets when available."""
        ctx = await agent._perceive_domain(pro_state, context_base)
        assert ctx.external_data["image_url"] == "https://cdn.shopify.com/refined.png"

    @pytest.mark.asyncio
    async def test_falls_back_to_raw_image(self, agent, context_base):
        """Should fall back to raw_input image_url when no refined_url."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/fallback.jpg"},
        )
        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["image_url"] == "https://cdn.shopify.com/fallback.jpg"

    @pytest.mark.asyncio
    async def test_extracts_hook_from_social_hooks(self, agent, context_base):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg"},
        )
        state.social_hooks = [{"caption": "Limited Edition!"}]
        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["hook_text"] == "Limited Edition!"

    @pytest.mark.asyncio
    async def test_hook_text_from_raw_input(self, agent, context_base):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={
                "image_url": "https://cdn.shopify.com/p.jpg",
                "hook_text": "From Raw",
            },
        )
        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["hook_text"] == "From Raw"

    @pytest.mark.asyncio
    async def test_extracts_brand_soul(self, agent, context_base):
        """Should extract brand_soul from strategic_intelligence or raw_input."""
        state = MissionState(
            product_id="product-123",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": "Handcrafted Ceramic Bowl",
                "product_name": "Handcrafted Ceramic Bowl",
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_name": "Kyoto Artisan",
                "hook_text": "New Collection",
                "brand_soul_enabled": True,
            },
        )
        state.visual_assets = {
            "refined_url": "https://cdn.shopify.com/refined.png",
            "original_image_url": "https://cdn.shopify.com/product.jpg",
        }
        ctx = await agent._perceive_domain(state, context_base)
        assert "brand_soul" in ctx.external_data


class TestActDomainNanoBananaPipeline:
    """Primary path: ProductAdGenerator via Nano Banana /edit."""

    @pytest.mark.asyncio
    async def test_calls_product_ad_generator(
        self, agent, pro_state, default_plan,
    ):
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "Japanese minimalism",
                "product_name": "Ceramic Bowl",
                "brand_name": "Kyoto Artisan",
                "hook_text": "",
            },
        )

        mock_ad_gen = MagicMock()
        mock_ad_gen.generate = AsyncMock(return_value=FAKE_AD_BYTES)

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://nano-ad.png")

        with patch(_AD_GEN, return_value=mock_ad_gen), \
             patch(_R2_SVC) as mock_r2_cls:

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="nano-key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        mock_ad_gen.generate.assert_called_once()
        call_kwargs = mock_ad_gen.generate.call_args.kwargs
        assert call_kwargs["image_url"] == "https://cdn.shopify.com/product.jpg"
        assert call_kwargs["product_name"] == "Ceramic Bowl"
        assert call_kwargs["brand_soul"] == "Japanese minimalism"
        assert call_kwargs["use_brand_style"] is False
        assert callable(call_kwargs["progress"])

        assert mock_r2_svc.upload_asset.call_count == 1
        assert actions[0].success is True
        assert state.visual_assets["ad_url"] == "r2://nano-ad.png"
        assert state.visual_progress["phase"] == "complete"

    @pytest.mark.asyncio
    async def test_emits_single_ad_url(
        self, agent, pro_state, default_plan,
    ):
        """Only one final ad image should be produced and uploaded."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",
            },
        )

        mock_ad_gen = MagicMock()
        mock_ad_gen.generate = AsyncMock(return_value=FAKE_AD_BYTES)

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://final.png")

        with patch(_AD_GEN, return_value=mock_ad_gen), \
             patch(_R2_SVC) as mock_r2_cls:

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert mock_r2_svc.upload_asset.call_count == 1
        assert state.visual_assets["ad_url"] == "r2://final.png"

    @pytest.mark.asyncio
    async def test_brand_style_disabled_by_default(
        self, agent, pro_state, default_plan,
    ):
        """use_brand_style must be False so the prompt stays fidelity-first."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "Rich brand context here",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",
            },
        )

        mock_ad_gen = MagicMock()
        mock_ad_gen.generate = AsyncMock(return_value=FAKE_AD_BYTES)

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://ad.png")

        with patch(_AD_GEN, return_value=mock_ad_gen), \
             patch(_R2_SVC) as mock_r2_cls:

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            await agent._act_domain(pro_state, context, default_plan)

        call_kwargs = mock_ad_gen.generate.call_args.kwargs
        assert call_kwargs["use_brand_style"] is False
        assert call_kwargs["brand_soul"] == "Rich brand context here"


class TestActDomainNoImage:
    @pytest.mark.asyncio
    async def test_no_image_skips(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"title": "No Image"},
        )
        context = AgentContext(raw_input={}, external_data={"image_url": ""})

        actions, _ = await agent._act_domain(state, context, default_plan)

        assert len(actions) == 1
        assert actions[0].success is False
        assert "No product/refined image URL" in actions[0].error


class TestActDomainFailure:
    @pytest.mark.asyncio
    async def test_nano_banana_failure(self, agent, pro_state, default_plan):
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",
            },
        )

        mock_ad_gen = MagicMock()
        mock_ad_gen.generate = AsyncMock(
            side_effect=RuntimeError("Nano Banana failed")
        )

        with patch(_AD_GEN, return_value=mock_ad_gen), \
             patch(_R2_SVC):
            actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert actions[0].success is False
        assert "Nano Banana failed" in actions[0].error
        assert state.visual_progress["phase"] == "error"

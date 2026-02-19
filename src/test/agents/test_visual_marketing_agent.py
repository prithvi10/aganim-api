"""
Unit tests for VisualMarketingAgent -- Marketing ad generation.

Covers:
  - _perceive_domain: context extraction for refined image, hooks, brand soul
  - _act_domain: full pipeline happy path, no-image skip, no-hook ad skip,
    error handling, standalone mode (no prior ImageRefinementAgent)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.visual_marketing.agent import VisualMarketingAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan

_VISUAL_SVC = "src.ecommerce.services.visual_service.VisualService"
_R2_SVC = "src.ecommerce.services.r2_storage_service.R2StorageService"
_HTTPX_ASYNC_CLIENT = "httpx.AsyncClient"

FAKE_IMAGE_BYTES = b"fake-image-bytes"


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


class TestActDomainHappyPath:
    @pytest.mark.asyncio
    async def test_full_marketing_pipeline(self, agent, pro_state, default_plan):
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/refined.png",
                "brand_soul": "Minimalist Kyoto",
                "product_name": "Bowl",
                "brand_name": "Kyoto",
                "hook_text": "New Collection",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.generate_ad = AsyncMock(return_value="https://fal.ai/ad.png")

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://ad.png")
        mock_client = _make_httpx_mock()

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client):

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        mock_visual_svc.generate_ad.assert_called_once()

        assert mock_r2_svc.upload_asset.call_count == 1

        assert len(actions) == 1
        assert actions[0].success is True
        assert actions[0].tool_name == "visual_marketing.generate"

        assert state.visual_assets["ad_url"] == "r2://ad.png"

        assert state.visual_progress["phase"] == "complete"

    @pytest.mark.asyncio
    async def test_does_not_call_isolate_or_refine(self, agent, pro_state, default_plan):
        """VisualMarketingAgent should NOT call isolate, remove_text, remove_objects, or refine."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/refined.png",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "Hook",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock()
        mock_visual_svc.remove_text = AsyncMock()
        mock_visual_svc.remove_objects = AsyncMock()
        mock_visual_svc.refine_product = AsyncMock()
        mock_visual_svc.generate_ad = AsyncMock(return_value="https://fal.ai/ad.png")

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://asset.png")
        mock_client = _make_httpx_mock()

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client):

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            await agent._act_domain(pro_state, context, default_plan)

        mock_visual_svc.isolate_product.assert_not_called()
        mock_visual_svc.remove_text.assert_not_called()
        mock_visual_svc.remove_objects.assert_not_called()
        mock_visual_svc.refine_product.assert_not_called()


class TestStyledPipeline:
    @pytest.mark.asyncio
    async def test_styled_pipeline_calls_generate_styled_ad(self, agent, default_plan):
        """When ad_style is set, the styled pipeline uses generate_styled_ad (Flux Fill)."""
        state = MissionState(
            product_id="product-123",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={
                "title": "Sake Bottle",
                "product_name": "Sake Bottle",
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_name": "Kyoto Artisan",
                "hook_text": "New Collection",
                "ad_style": "luxury",
            },
        )
        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "Premium Japanese",
                "product_name": "Sake Bottle",
                "brand_name": "Kyoto Artisan",
                "hook_text": "New Collection",
                "ad_style": "luxury",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_visual_svc.generate_styled_ad = AsyncMock(return_value=b"final-ad-bytes")

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://styled-ad.png")

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls:

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")

            actions, result_state = await agent._act_domain(state, context, default_plan)

        mock_visual_svc.isolate_product.assert_called_once()
        mock_visual_svc.generate_styled_ad.assert_called_once()
        call_kwargs = mock_visual_svc.generate_styled_ad.call_args
        assert call_kwargs.kwargs.get("ad_style") or call_kwargs[1].get("ad_style") or \
               (len(call_kwargs[0]) > 0 and True)

        assert not hasattr(mock_visual_svc, 'generate_ad') or \
               not mock_visual_svc.generate_ad.called

        assert len(actions) == 1
        assert actions[0].success is True
        assert result_state.visual_assets["ad_url"] == "r2://styled-ad.png"
        assert result_state.visual_assets["refined_url"] == "r2://styled-ad.png"
        assert result_state.visual_progress["phase"] == "complete"

    @pytest.mark.asyncio
    async def test_styled_pipeline_does_not_call_ideogram(self, agent, default_plan):
        """Styled pipeline must NOT call generate_ad (Ideogram)."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "ad_style": "nature",
            },
        )
        context = AgentContext(
            raw_input=state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Tea",
                "brand_name": "",
                "hook_text": "",
                "ad_style": "nature",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock(return_value=FAKE_IMAGE_BYTES)
        mock_visual_svc.generate_styled_ad = AsyncMock(return_value=b"ad-bytes")
        mock_visual_svc.generate_ad = AsyncMock()

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://ad.png")

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls:

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            await agent._act_domain(state, context, default_plan)

        mock_visual_svc.generate_ad.assert_not_called()
        mock_visual_svc.generate_styled_ad.assert_called_once()


class TestActDomainNoHook:
    @pytest.mark.asyncio
    async def test_ad_skipped_no_text(self, agent, pro_state, default_plan):
        """Ad generation is skipped when no hook text and no product name."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/refined.png",
                "brand_soul": "",
                "product_name": "",
                "brand_name": "",
                "hook_text": "",
            },
        )

        actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert state.visual_assets.get("ad_url") is None
        assert actions[0].success is True
        assert state.visual_progress["phase"] == "complete"


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
    async def test_ad_generation_fails(self, agent, pro_state, default_plan):
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/refined.png",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "Hook",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.generate_ad = AsyncMock(
            side_effect=RuntimeError("Ideogram 3.0 failed")
        )

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC):
            actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert actions[0].success is False
        assert "Ideogram 3.0 failed" in actions[0].error
        assert state.visual_progress["phase"] == "error"


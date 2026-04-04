"""
Unit tests for ImageRefinementAgent -- AI product photo cleanup via Nano Banana.

Covers:
  - _perceive_domain: context extraction for image URL, brand soul
  - _act_domain: full pipeline happy path (Nano Banana /edit),
    no-image skip, SSRF rejection, error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.image_refinement.agent import ImageRefinementAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction

_FAL_CLIENT = "src.ecommerce.services.visual_service._get_fal_client"
_R2_SVC = "src.ecommerce.services.r2_storage_service.R2StorageService"
_HTTPX_ASYNC_CLIENT = "httpx.AsyncClient"

FAKE_IMAGE_BYTES = b"fake-image-bytes"
FAKE_FAL_RESULT = {"images": [{"url": "https://fal.ai/refined.png"}]}


def _make_httpx_mock(response_content=FAKE_IMAGE_BYTES):
    mock_response = MagicMock()
    mock_response.content = response_content
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _make_fal_client_mock(result=None):
    mock_fal = MagicMock()
    mock_fal.subscribe = MagicMock(return_value=result or FAKE_FAL_RESULT)
    return mock_fal


@pytest.fixture
def mock_services():
    services = MagicMock()
    services.rag.get_brand_context = AsyncMock(return_value=[])
    return services


@pytest.fixture
def agent(mock_services):
    return ImageRefinementAgent("test-shop.myshopify.com", services=mock_services)


@pytest.fixture
def pro_state():
    return MissionState(
        product_id="product-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "product_name": "Handcrafted Ceramic Bowl",
            "image_url": "https://cdn.shopify.com/product.jpg",
        },
    )


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
        steps=["refine_image"],
        selected_tools=["image_refinement.generate"],
        confidence=1.0,
        reasoning="Image refinement pipeline",
    )


class TestImageRefinementAgentAttributes:
    def test_role_name(self):
        assert ImageRefinementAgent.role_name == "ImageRefinement"

    def test_requires_no_llm(self):
        assert ImageRefinementAgent.requires_llm_reasoning is False

    def test_default_tool(self):
        assert ImageRefinementAgent.default_tool == "image_refinement.generate"


class TestPerceiveDomain:
    @pytest.mark.asyncio
    async def test_extracts_image_url(self, agent, pro_state, context_base):
        ctx = await agent._perceive_domain(pro_state, context_base)
        assert ctx.external_data["image_url"] == "https://cdn.shopify.com/product.jpg"

    @pytest.mark.asyncio
    async def test_extracts_product_name(self, agent, pro_state, context_base):
        ctx = await agent._perceive_domain(pro_state, context_base)
        assert ctx.external_data["product_name"] == "Handcrafted Ceramic Bowl"

    @pytest.mark.asyncio
    async def test_no_image_url_empty(self, agent, context_base):
        state = MissionState(
            product_id="p1",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={"title": "No image"},
        )
        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["image_url"] == ""

    @pytest.mark.asyncio
    async def test_brand_soul_from_strategic_intelligence(self, agent, context_base):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://cdn.shopify.com/p.jpg", "brand_soul_enabled": True},
        )
        context_base.strategic_intelligence = {"archetype": "Artisan", "tone": "refined"}
        ctx = await agent._perceive_domain(state, context_base)
        assert "Artisan" in ctx.external_data["brand_soul"]

    @pytest.mark.asyncio
    async def test_does_not_extract_hook_text(self, agent, pro_state, context_base):
        """ImageRefinementAgent does NOT need hook_text (no ad generation)."""
        ctx = await agent._perceive_domain(pro_state, context_base)
        assert "hook_text" not in ctx.external_data


class TestActDomainHappyPath:
    @pytest.mark.asyncio
    async def test_full_refinement_pipeline(self, agent, pro_state, default_plan):
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "Minimalist Kyoto",
                "product_name": "Bowl",
            },
        )

        mock_fal = _make_fal_client_mock()
        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://refined.png")
        mock_client = _make_httpx_mock()

        with patch(_FAL_CLIENT, return_value=mock_fal), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client):

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        mock_fal.subscribe.assert_called_once()
        call_args = mock_fal.subscribe.call_args
        assert call_args[0][0] == "fal-ai/nano-banana/edit"
        assert "https://cdn.shopify.com/product.jpg" in call_args[1]["arguments"]["image_urls"]
        assert "fidelity" in call_args[1]["arguments"]["prompt"].lower()

        mock_r2_svc.upload_asset.assert_called_once()

        assert len(actions) == 1
        assert actions[0].success is True
        assert actions[0].tool_name == "image_refinement.generate"

        assert state.visual_assets is not None
        assert state.visual_assets["refined_url"] == "r2://refined.png"
        assert state.visual_assets["ad_url"] is None
        assert state.visual_assets["hero_url"] is None

        assert state.visual_progress["phase"] == "complete"
        assert state.visual_progress["pct"] == 100

    @pytest.mark.asyncio
    async def test_does_not_use_visual_service(self, agent, pro_state, default_plan):
        """ImageRefinementAgent no longer uses VisualService (no isolate/refine)."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
            },
        )

        mock_fal = _make_fal_client_mock()
        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://asset.png")
        mock_client = _make_httpx_mock()

        with patch(_FAL_CLIENT, return_value=mock_fal), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client), \
             patch("src.ecommerce.services.visual_service.VisualService") as mock_vs:

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            await agent._act_domain(pro_state, context, default_plan)

        mock_vs.assert_not_called()


class TestActDomainNoImage:
    @pytest.mark.asyncio
    async def test_no_image_url_skips(self, agent, default_plan):
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"title": "No Image"},
        )
        context = AgentContext(raw_input={}, external_data={"image_url": ""})

        actions, result_state = await agent._act_domain(state, context, default_plan)

        assert len(actions) == 1
        assert actions[0].success is False
        assert "No product image URL" in actions[0].error


class TestActDomainURLValidation:
    @pytest.mark.asyncio
    async def test_internal_ip_rejected(self, agent, pro_state, default_plan):
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://169.254.169.254/latest/meta-data/img.png",
                "brand_soul": "",
                "product_name": "Bowl",
            },
        )

        actions, _ = await agent._act_domain(pro_state, context, default_plan)
        assert actions[0].success is False
        assert "not in the trusted allow-list" in actions[0].error


class TestActDomainFailure:
    @pytest.mark.asyncio
    async def test_nano_banana_call_fails(self, agent, pro_state, default_plan):
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
            },
        )

        mock_fal = MagicMock()
        mock_fal.subscribe = MagicMock(side_effect=RuntimeError("fal.ai timeout"))

        with patch(_FAL_CLIENT, return_value=mock_fal), \
             patch(_R2_SVC):
            actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert actions[0].success is False
        assert "fal.ai timeout" in actions[0].error
        assert state.visual_progress["phase"] == "error"

    @pytest.mark.asyncio
    async def test_bad_fal_result_fails(self, agent, pro_state, default_plan):
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
            },
        )

        mock_fal = _make_fal_client_mock(result={"images": []})

        with patch(_FAL_CLIENT, return_value=mock_fal), \
             patch(_R2_SVC):
            actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert actions[0].success is False
        assert state.visual_assets["refined_url"] is None
        assert state.visual_assets["original_image_url"] == "https://cdn.shopify.com/product.jpg"


class TestExtractUrl:
    def test_extract_from_images_list(self):
        result = {"images": [{"url": "https://fal.ai/img.png"}]}
        assert ImageRefinementAgent._extract_url(result) == "https://fal.ai/img.png"

    def test_extract_from_image_dict(self):
        result = {"image": {"url": "https://fal.ai/img2.png"}}
        assert ImageRefinementAgent._extract_url(result) == "https://fal.ai/img2.png"

    def test_extract_from_image_string(self):
        result = {"image": "https://fal.ai/img3.png"}
        assert ImageRefinementAgent._extract_url(result) == "https://fal.ai/img3.png"

    def test_empty_result_raises(self):
        with pytest.raises(ValueError, match="Could not extract"):
            ImageRefinementAgent._extract_url({})

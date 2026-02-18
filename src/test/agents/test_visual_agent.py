"""
Unit tests for VisualAgent -- Pro-Visual autonomous image generation pipeline.

Covers:
  - _perceive_domain: context extraction for image URL, brand soul, hooks
  - _act_domain: full pipeline happy path, no-image skip, ad-skip (no hook),
    error handling, partial results on failure
  - _publish_visual_assets: publish to Shopify Media Library
  - Edge cases and failure paths
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.visual.agent import VisualAgent
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction

# Patch targets — VisualService / R2StorageService / upload_media_to_shopify are
# imported **locally** inside method bodies, so patch them at their source modules.
_VISUAL_SVC = "src.ecommerce.services.visual_service.VisualService"
_R2_SVC = "src.ecommerce.services.r2_storage_service.R2StorageService"
_UPLOAD_MEDIA = "src.ecommerce.services.shopify_service.upload_media_to_shopify"
_ADD_PRODUCT_IMAGE = "src.ecommerce.services.shopify_service.add_product_image"
_HTTPX_ASYNC_CLIENT = "httpx.AsyncClient"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Mock ServiceRegistry."""
    services = MagicMock()
    services.rag.get_brand_context = AsyncMock(return_value=[])
    return services


@pytest.fixture
def agent(mock_services):
    """Create a VisualAgent."""
    return VisualAgent("test-shop.myshopify.com", services=mock_services)


@pytest.fixture
def pro_state():
    """Pro-tier state with image URL."""
    return MissionState(
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
        autonomous=True,
    )


@pytest.fixture
def state_no_image():
    """State with no image URL."""
    return MissionState(
        product_id="product-456",
        shop_id="test-shop.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": "Test Product",
        },
    )


@pytest.fixture
def context_base():
    """Base AgentContext."""
    return AgentContext(
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "product_name": "Handcrafted Ceramic Bowl",
            "image_url": "https://cdn.shopify.com/product.jpg",
            "brand_name": "Kyoto Artisan",
            "hook_text": "New Collection",
        },
    )


@pytest.fixture
def default_plan():
    """A default AgentPlan."""
    return AgentPlan(
        steps=["generate_visuals"],
        selected_tools=["visual.generate"],
        confidence=1.0,
        reasoning="Visual pipeline execution",
    )


FAKE_MASKED = b"fake-masked-bytes"
FAKE_IMAGE_BYTES = b"fake-image-bytes"


def _make_httpx_mock(response_content=FAKE_IMAGE_BYTES):
    """Create a mock httpx.AsyncClient context manager with a response."""
    mock_response = MagicMock()
    mock_response.content = response_content
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# =============================================================================
# Tests: Class attributes
# =============================================================================

class TestVisualAgentAttributes:
    """Test VisualAgent class-level attributes."""

    def test_role_name(self):
        assert VisualAgent.role_name == "Visual"

    def test_requires_no_llm(self):
        assert VisualAgent.requires_llm_reasoning is False

    def test_default_tool(self):
        assert VisualAgent.default_tool == "visual.generate"

    def test_publish_map_has_visual_refine(self):
        assert "visual/product-refine" in VisualAgent.PUBLISH_MAP
        assert VisualAgent.PUBLISH_MAP["visual/product-refine"] == "_publish_visual_assets"


# =============================================================================
# Tests: _perceive_domain
# =============================================================================

class TestPerceiveDomain:
    """Test _perceive_domain context extraction."""

    @pytest.mark.asyncio
    async def test_extracts_image_url(self, agent, pro_state, context_base):
        ctx = await agent._perceive_domain(pro_state, context_base)
        assert ctx.external_data["image_url"] == "https://cdn.shopify.com/product.jpg"

    @pytest.mark.asyncio
    async def test_extracts_brand_name(self, agent, pro_state, context_base):
        ctx = await agent._perceive_domain(pro_state, context_base)
        assert ctx.external_data["brand_name"] == "Kyoto Artisan"

    @pytest.mark.asyncio
    async def test_extracts_product_name(self, agent, pro_state, context_base):
        ctx = await agent._perceive_domain(pro_state, context_base)
        assert ctx.external_data["product_name"] == "Handcrafted Ceramic Bowl"

    @pytest.mark.asyncio
    async def test_extracts_hook_text_from_raw_input(self, agent, pro_state, context_base):
        ctx = await agent._perceive_domain(pro_state, context_base)
        assert ctx.external_data["hook_text"] == "New Collection"

    @pytest.mark.asyncio
    async def test_extracts_hook_from_social_hooks_dict(self, agent, context_base):
        """Test hook extraction from state.social_hooks (dict format)."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://img.com/p.jpg"},
        )
        state.social_hooks = [{"caption": "Limited Edition!", "text": "fallback"}]

        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["hook_text"] == "Limited Edition!"

    @pytest.mark.asyncio
    async def test_hook_fallback_to_text_key(self, agent, context_base):
        """Test hook extraction falls back to 'text' key."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://img.com/p.jpg"},
        )
        state.social_hooks = [{"text": "Artisan Made"}]

        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["hook_text"] == "Artisan Made"

    @pytest.mark.asyncio
    async def test_no_hooks_fallback_to_raw_input(self, agent, context_base):
        """Test hook_text falls back to raw_input when no social_hooks."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://img.com/p.jpg", "hook_text": "From Raw"},
        )
        state.social_hooks = None

        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["hook_text"] == "From Raw"

    @pytest.mark.asyncio
    async def test_empty_hooks_and_no_raw(self, agent, context_base):
        """Test hook_text is empty when no hooks and no raw_input hook."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://img.com/p.jpg"},
        )
        state.social_hooks = []

        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["hook_text"] == ""

    @pytest.mark.asyncio
    async def test_no_image_url_logs_warning(self, agent, context_base):
        """Test warning logged when no image URL is found."""
        state = MissionState(
            product_id="p1",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={"title": "No image product"},
        )

        ctx = await agent._perceive_domain(state, context_base)
        assert ctx.external_data["image_url"] == ""

    @pytest.mark.asyncio
    async def test_image_url_alternative_keys(self, agent, context_base):
        """Test image URL extraction from alternative raw_input keys."""
        for key in ("product_image_url", "image_src"):
            state = MissionState(
                product_id="p1",
                shop_id="s1",
                plan_tier="Pro",
                raw_input={key: "https://cdn.shopify.com/alt.jpg"},
            )
            ctx = await agent._perceive_domain(state, context_base)
            assert ctx.external_data["image_url"] == "https://cdn.shopify.com/alt.jpg"

    @pytest.mark.asyncio
    async def test_brand_soul_from_strategic_intelligence(self, agent, context_base):
        """Test brand_soul extracted from strategic_intelligence."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://img.com/p.jpg"},
        )
        context_base.strategic_intelligence = {"archetype": "Artisan", "tone": "refined"}

        ctx = await agent._perceive_domain(state, context_base)
        assert "Artisan" in ctx.external_data["brand_soul"]

    @pytest.mark.asyncio
    async def test_brand_soul_from_raw_input_fallback(self, agent, context_base):
        """Test brand_soul falls back to raw_input brand_context."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={
                "image_url": "https://img.com/p.jpg",
                "brand_context": "Traditional Japanese craftsmanship",
            },
        )
        context_base.strategic_intelligence = None

        ctx = await agent._perceive_domain(state, context_base)
        assert "Japanese craftsmanship" in ctx.external_data["brand_soul"]

    @pytest.mark.asyncio
    async def test_brand_soul_truncated(self, agent, context_base):
        """Test brand_soul is truncated to 600 chars."""
        state = MissionState(
            product_id="p1",
            shop_id="s1",
            plan_tier="Pro",
            raw_input={"image_url": "https://img.com/p.jpg"},
        )
        context_base.strategic_intelligence = {"long": "A" * 1000}

        ctx = await agent._perceive_domain(state, context_base)
        assert len(ctx.external_data["brand_soul"]) <= 600


# =============================================================================
# Tests: _act_domain -- Happy path
# =============================================================================

class TestActDomainHappyPath:
    """Test _act_domain with full pipeline execution."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_hook(self, agent, pro_state, default_plan):
        """Test complete pipeline: masking → refine → ad → hero."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "Minimalist Kyoto",
                "product_name": "Bowl",
                "brand_name": "Kyoto",
                "hook_text": "New Collection",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.remove_text = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.refine_product = AsyncMock(return_value="https://fal.ai/refined.png")
        mock_visual_svc.generate_ad = AsyncMock(return_value="https://fal.ai/ad.png")
        mock_visual_svc.expand_hero = AsyncMock(return_value="https://fal.ai/hero.png")

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(side_effect=[
            "r2://masked.png",    # masked upload
            "r2://refined.png",   # refined upload
            "r2://ad.png",        # ad upload
            "r2://hero.png",      # hero upload
        ])

        mock_client = _make_httpx_mock()

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client):

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="test-key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        # Verify all services were called
        mock_visual_svc.isolate_product.assert_called_once()
        mock_visual_svc.refine_product.assert_called_once()
        mock_visual_svc.generate_ad.assert_called_once()
        mock_visual_svc.expand_hero.assert_called_once()

        # Verify R2 uploads (masked + refined + ad + hero = 4)
        assert mock_r2_svc.upload_asset.call_count == 4

        # Verify actions
        assert len(actions) == 1
        assert actions[0].success is True
        assert actions[0].tool_name == "visual.generate"

        # Verify state updated
        assert state.visual_assets is not None
        assert state.visual_assets["refined_url"] == "r2://refined.png"
        assert state.visual_assets["ad_url"] == "r2://ad.png"
        assert state.visual_assets["hero_url"] == "r2://hero.png"

        # Progress should reach 100%
        assert state.visual_progress["phase"] == "complete"
        assert state.visual_progress["pct"] == 100


# =============================================================================
# Tests: _act_domain -- No image URL (skip)
# =============================================================================

class TestActDomainNoImage:
    """Test _act_domain when no image URL is provided."""

    @pytest.mark.asyncio
    async def test_no_image_url_skips_pipeline(self, agent, state_no_image, default_plan):
        """Pipeline should be skipped with a failure action."""
        context = AgentContext(
            raw_input=state_no_image.raw_input,
            external_data={"image_url": ""},
        )

        actions, state = await agent._act_domain(state_no_image, context, default_plan)

        assert len(actions) == 1
        assert actions[0].success is False
        assert actions[0].error == "No product image URL provided"
        assert "Skipped" in state.logs[-1]

    @pytest.mark.asyncio
    async def test_no_image_url_no_visual_assets(self, agent, state_no_image, default_plan):
        """State should NOT have visual_assets set when skipped."""
        context = AgentContext(
            raw_input=state_no_image.raw_input,
            external_data={"image_url": ""},
        )

        _, state = await agent._act_domain(state_no_image, context, default_plan)

        assert state.visual_assets is None


# =============================================================================
# Tests: _act_domain -- SSRF URL validation
# =============================================================================

class TestActDomainURLValidation:
    """Test _act_domain rejects untrusted image URLs (SSRF prevention)."""

    @pytest.mark.asyncio
    async def test_internal_ip_url_rejected(self, agent, pro_state, default_plan):
        """AWS metadata endpoint should be blocked."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://169.254.169.254/latest/meta-data/img.png",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",
            },
        )

        actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert len(actions) == 1
        assert actions[0].success is False
        assert "url_validation_failed" in str(actions[0].input_params)
        assert "not in the trusted allow-list" in actions[0].error

    @pytest.mark.asyncio
    async def test_http_url_rejected(self, agent, pro_state, default_plan):
        """Non-HTTPS URLs should be blocked."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "http://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",
            },
        )

        actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert actions[0].success is False
        assert "HTTPS" in actions[0].error

    @pytest.mark.asyncio
    async def test_evil_domain_rejected(self, agent, pro_state, default_plan):
        """Random external domains should be blocked."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://evil.com/steal-data.png",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",
            },
        )

        actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert actions[0].success is False
        assert "not in the trusted allow-list" in actions[0].error
        # Pipeline should NOT have been started
        assert state.visual_assets is None

    @pytest.mark.asyncio
    async def test_valid_shopify_url_passes_validation(self, agent, pro_state, default_plan):
        """Valid Shopify CDN URL should pass validation and enter the pipeline."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/s/files/1/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.remove_text = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.refine_product = AsyncMock(return_value="https://fal.ai/refined.png")
        mock_visual_svc.expand_hero = AsyncMock(return_value="https://fal.ai/hero.png")

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://asset.png")

        mock_client = _make_httpx_mock()

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client):

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        # Pipeline should have started (isolate_product called)
        mock_visual_svc.isolate_product.assert_called_once()
        assert actions[0].success is True


# =============================================================================
# Tests: _act_domain -- No hook text (ad skipped)
# =============================================================================

class TestActDomainNoHook:
    """Test _act_domain when no hook text is provided (ad generation skipped)."""

    @pytest.mark.asyncio
    async def test_ad_skipped_when_no_hook(self, agent, pro_state, default_plan):
        """Ad generation should be skipped when hook_text is empty."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",  # No hook
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.remove_text = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.refine_product = AsyncMock(return_value="https://fal.ai/refined.png")
        mock_visual_svc.generate_ad = AsyncMock()  # Should NOT be called
        mock_visual_svc.expand_hero = AsyncMock(return_value="https://fal.ai/hero.png")

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(side_effect=[
            "r2://masked.png",
            "r2://refined.png",
            "r2://hero.png",
        ])

        mock_client = _make_httpx_mock()

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client):

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        # Ad generation should NOT be called
        mock_visual_svc.generate_ad.assert_not_called()

        # ad_url should be None
        assert state.visual_assets["ad_url"] is None
        # refined and hero should still be set
        assert state.visual_assets["refined_url"] is not None
        assert state.visual_assets["hero_url"] is not None

        # Action should still be successful
        assert actions[0].success is True

        # Should have a log about ad being skipped
        ad_skip_logs = [l for l in state.logs if "Ad generation skipped" in l]
        assert len(ad_skip_logs) > 0


# =============================================================================
# Tests: _act_domain -- Pipeline failure
# =============================================================================

class TestActDomainFailure:
    """Test _act_domain when the pipeline fails midway."""

    @pytest.mark.asyncio
    async def test_isolate_product_fails(self, agent, pro_state, default_plan):
        """Test pipeline failure at product isolation step."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "Test",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock(
            side_effect=RuntimeError("rembg model crashed")
        )

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC):

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert len(actions) == 1
        assert actions[0].success is False
        assert "rembg model crashed" in actions[0].error

        # State should have partial visual_assets with original URL
        assert state.visual_assets["original_image_url"] == "https://cdn.shopify.com/product.jpg"
        assert state.visual_assets["refined_url"] is None

        # Progress should show error
        assert state.visual_progress["phase"] == "error"

    @pytest.mark.asyncio
    async def test_refine_fails_after_masking(self, agent, pro_state, default_plan):
        """Test partial failure: masking succeeds but refinement fails."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "Test",
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.remove_text = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.refine_product = AsyncMock(
            side_effect=ValueError("fal.ai returned empty result")
        )

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(return_value="r2://masked.png")

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls:

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert actions[0].success is False
        assert "empty result" in actions[0].error

        # Partial results: masking succeeded but refined_url is None
        assert state.visual_assets["original_image_url"] == "https://cdn.shopify.com/product.jpg"
        assert state.visual_assets["refined_url"] is None

    @pytest.mark.asyncio
    async def test_hero_fails_after_refine(self, agent, pro_state, default_plan):
        """Test partial failure: refine succeeds but hero expansion fails."""
        context = AgentContext(
            raw_input=pro_state.raw_input,
            external_data={
                "image_url": "https://cdn.shopify.com/product.jpg",
                "brand_soul": "",
                "product_name": "Bowl",
                "brand_name": "",
                "hook_text": "",  # no ad
            },
        )

        mock_visual_svc = MagicMock()
        mock_visual_svc.isolate_product = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.remove_text = AsyncMock(return_value=FAKE_MASKED)
        mock_visual_svc.refine_product = AsyncMock(return_value="https://fal.ai/refined.png")
        mock_visual_svc.expand_hero = AsyncMock(
            side_effect=TimeoutError("fal.ai timed out")
        )

        mock_r2_svc = MagicMock()
        mock_r2_svc.upload_asset = AsyncMock(side_effect=[
            "r2://masked.png",
            "r2://refined.png",
        ])

        mock_client = _make_httpx_mock()

        with patch(_VISUAL_SVC, return_value=mock_visual_svc), \
             patch(_R2_SVC) as mock_r2_cls, \
             patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client):

            mock_r2_cls.return_value = mock_r2_svc
            mock_r2_cls.build_key = MagicMock(return_value="key")

            actions, state = await agent._act_domain(pro_state, context, default_plan)

        assert actions[0].success is False
        # Partial results: refined_url was set before the error
        assert state.visual_assets["refined_url"] == "r2://refined.png"
        assert state.visual_assets["hero_url"] is None


# =============================================================================
# Tests: _publish_visual_assets
# =============================================================================

class TestPublishVisualAssets:
    """Test _publish_visual_assets method."""

    @pytest.mark.asyncio
    async def test_publish_all_three_assets(self, agent):
        """Test publishing all three asset types to Shopify."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"product_name": "Bowl"},
            autonomous=True,
        )
        state.visual_assets = {
            "refined_url": "https://r2.example.com/refined.png",
            "ad_url": "https://r2.example.com/ad.png",
            "hero_url": "https://r2.example.com/hero.png",
        }
        creds = {"access_token": "shpat_test"}

        mock_client = _make_httpx_mock()

        with patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client), \
             patch(_UPLOAD_MEDIA, new_callable=AsyncMock) as mock_upload, \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock) as mock_add_img:

            await agent._publish_visual_assets(state, creds)

        # Refined goes via add_product_image, ad + hero via upload_media
        assert mock_add_img.call_count == 1
        assert mock_upload.call_count == 2

        # Check logs: 1 refined added + 2 media published
        all_logs = "\n".join(state.logs)
        assert "Refined image added" in all_logs or "refined image" in all_logs.lower()
        publish_logs = [l for l in state.logs if "Published" in l]
        assert len(publish_logs) == 2

    @pytest.mark.asyncio
    async def test_publish_skips_missing_assets(self, agent):
        """Test publish skips asset types that have no URL."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"product_name": "Bowl"},
            autonomous=True,
        )
        state.visual_assets = {
            "refined_url": "https://r2.example.com/refined.png",
            "ad_url": None,  # no ad
            "hero_url": None,  # no hero
        }
        creds = {"access_token": "shpat_test"}

        mock_client = _make_httpx_mock()

        with patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client), \
             patch(_UPLOAD_MEDIA, new_callable=AsyncMock) as mock_upload, \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock) as mock_add_img:

            await agent._publish_visual_assets(state, creds)

        # Only refined via add_product_image, nothing via upload_media
        assert mock_add_img.call_count == 1
        assert mock_upload.call_count == 0

    @pytest.mark.asyncio
    async def test_publish_no_access_token(self, agent):
        """Test publish is skipped when no access token is provided."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"product_name": "Bowl"},
        )
        state.visual_assets = {
            "refined_url": "https://r2.example.com/refined.png",
        }

        await agent._publish_visual_assets(state, {"access_token": ""})

        skip_logs = [l for l in state.logs if "missing Shopify credentials" in l]
        assert len(skip_logs) == 1

    @pytest.mark.asyncio
    async def test_publish_no_visual_assets(self, agent):
        """Test publish handles None visual_assets gracefully."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )
        state.visual_assets = None

        # Should not raise
        await agent._publish_visual_assets(state, {"access_token": "shpat_test"})

    @pytest.mark.asyncio
    async def test_publish_individual_asset_failure_continues(self, agent):
        """Test that failure to publish one asset doesn't stop others."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"product_name": "Bowl"},
        )
        state.visual_assets = {
            "refined_url": "https://r2.example.com/refined.png",
            "ad_url": "https://r2.example.com/ad.png",
            "hero_url": "https://r2.example.com/hero.png",
        }
        creds = {"access_token": "shpat_test"}

        upload_call_count = 0

        async def flaky_upload(**kwargs):
            nonlocal upload_call_count
            upload_call_count += 1
            if upload_call_count == 1:  # first media upload (ad) fails
                raise Exception("Upload failed for ad")
            return "gid://shopify/File/123"

        mock_client = _make_httpx_mock()

        with patch(_HTTPX_ASYNC_CLIENT, return_value=mock_client), \
             patch(_UPLOAD_MEDIA, side_effect=flaky_upload), \
             patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock) as mock_add_img:

            await agent._publish_visual_assets(state, creds)

        # Refined via add_product_image, ad + hero via upload_media
        assert mock_add_img.call_count == 1
        assert upload_call_count == 2  # ad (fail) + hero (success)

        # Should have success and failure logs
        success_logs = [l for l in state.logs if "Published" in l or "Refined image added" in l]
        failure_logs = [l for l in state.logs if "Failed" in l]
        assert len(success_logs) >= 2  # refined added + hero published
        assert len(failure_logs) >= 1  # ad failed

    @pytest.mark.asyncio
    async def test_publish_download_failure(self, agent):
        """Test publish handles failure in add_product_image for refined."""
        state = MissionState(
            product_id="p1",
            shop_id="shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"product_name": "Bowl"},
        )
        state.visual_assets = {
            "refined_url": "https://r2.example.com/refined.png",
            "ad_url": None,
            "hero_url": None,
        }
        creds = {"access_token": "shpat_test"}

        with patch(_ADD_PRODUCT_IMAGE, new_callable=AsyncMock,
                    side_effect=Exception("productCreateMedia failed")):
            # Should not raise -- individual failures are caught
            await agent._publish_visual_assets(state, creds)

        failure_logs = [l for l in state.logs if "Failed" in l]
        assert len(failure_logs) == 1

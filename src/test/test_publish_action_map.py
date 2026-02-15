"""
Unit tests for PUBLISH_ACTION_MAP handlers in agent_actions.py.

Tests publish_seo_fields, publish_variant_price, publish_meta_post,
publish_flow_campaign, and publish_value_metafields.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.core.agent_actions import (
    PUBLISH_ACTION_MAP,
    publish_seo_fields,
    publish_variant_price,
    publish_meta_post,
    publish_flow_campaign,
    publish_value_metafields,
)


# =============================================================================
# Tests: PUBLISH_ACTION_MAP registry
# =============================================================================

class TestPublishActionMapRegistry:
    """Tests for the PUBLISH_ACTION_MAP dictionary."""

    def test_contains_expected_keys(self):
        """Test that all expected action names are registered."""
        expected = [
            "seo_optimize",
            "price_scout",
            "social_hook_architect",
            "seasonal_campaign_agent",
            "seasonal_campaign_caption",
            "value_discovery",
        ]
        for key in expected:
            assert key in PUBLISH_ACTION_MAP, f"Missing key: {key}"

    def test_all_values_are_callable(self):
        """Test that all registered handlers are callable."""
        for key, handler in PUBLISH_ACTION_MAP.items():
            assert callable(handler), f"Handler for '{key}' is not callable"

    def test_maps_to_correct_handlers(self):
        """Test that action names map to the correct handler functions."""
        assert PUBLISH_ACTION_MAP["seo_optimize"] is publish_seo_fields
        assert PUBLISH_ACTION_MAP["price_scout"] is publish_variant_price
        assert PUBLISH_ACTION_MAP["social_hook_architect"] is publish_meta_post
        assert PUBLISH_ACTION_MAP["seasonal_campaign_agent"] is publish_flow_campaign
        assert PUBLISH_ACTION_MAP["seasonal_campaign_caption"] is publish_meta_post
        assert PUBLISH_ACTION_MAP["value_discovery"] is publish_value_metafields


# =============================================================================
# Tests: publish_seo_fields
# =============================================================================

class TestPublishSeoFields:
    """Tests for the publish_seo_fields handler."""

    @pytest.mark.asyncio
    async def test_success_with_dict_content(self):
        """Test SEO publish with dict content containing title and description."""
        mock_db = MagicMock()
        content = {"seo_title": "Best Product", "seo_description": "Great quality product"}

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={"access_token": "shpat_test"}), \
             patch("src.ecommerce.services.shopify_service.update_product_seo", new_callable=AsyncMock) as mock_update:

            result = await publish_seo_fields(
                db=mock_db,
                shop="test.myshopify.com",
                content=content,
                product_id="123",
                context={},
            )

            mock_update.assert_called_once_with(
                shop_domain="test.myshopify.com",
                access_token="shpat_test",
                product_id="123",
                seo_title="Best Product",
                seo_description="Great quality product",
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_success_with_json_string_content(self):
        """Test SEO publish with JSON string content."""
        mock_db = MagicMock()
        import json
        content = json.dumps({"seo_title": "Title", "seo_description": "Desc"})

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={"access_token": "shpat_test"}), \
             patch("src.ecommerce.services.shopify_service.update_product_seo", new_callable=AsyncMock) as mock_update:

            await publish_seo_fields(
                db=mock_db,
                shop="test.myshopify.com",
                content=content,
                product_id="123",
                context={},
            )

            mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_missing_credentials(self):
        """Test that missing credentials raises ValueError."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={}):
            with pytest.raises(ValueError, match="missing_credentials"):
                await publish_seo_fields(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content={"seo_title": "Test"},
                    product_id="123",
                    context={},
                )

    @pytest.mark.asyncio
    async def test_raises_when_no_seo_data(self):
        """Test that missing SEO title and description raises ValueError."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={"access_token": "shpat_test"}):
            with pytest.raises(ValueError, match="seo_title or seo_description required"):
                await publish_seo_fields(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content={},
                    product_id="123",
                    context={},
                )

    @pytest.mark.asyncio
    async def test_falls_back_to_context_for_seo_data(self):
        """Test that SEO data can come from context dict."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={"access_token": "shpat_test"}), \
             patch("src.ecommerce.services.shopify_service.update_product_seo", new_callable=AsyncMock) as mock_update:

            await publish_seo_fields(
                db=mock_db,
                shop="test.myshopify.com",
                content={},
                product_id="123",
                context={"seo_title": "From Context", "seo_description": "Also from context"},
            )

            mock_update.assert_called_once()
            call_kwargs = mock_update.call_args.kwargs
            assert call_kwargs["seo_title"] == "From Context"


# =============================================================================
# Tests: publish_variant_price
# =============================================================================

class TestPublishVariantPrice:
    """Tests for the publish_variant_price handler."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Test successful price publish."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
            "price_guardrails": {"min_price": 5, "max_price": 500},
        }), patch("src.ecommerce.services.shopify_service.update_variant_price", new_callable=AsyncMock) as mock_update:

            await publish_variant_price(
                db=mock_db,
                shop="test.myshopify.com",
                content={"recommended_price": 29.99},
                product_id="123",
                context={"variant_id": "var_456"},
            )

            mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_price_below_guardrail(self):
        """Test that price below min guardrail raises ValueError."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
            "price_guardrails": {"min_price": 10, "max_price": 500},
        }):
            with pytest.raises(ValueError, match="price_outside_guardrails"):
                await publish_variant_price(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content={"recommended_price": 5},
                    product_id="123",
                    context={"variant_id": "var_456"},
                )

    @pytest.mark.asyncio
    async def test_raises_when_price_above_guardrail(self):
        """Test that price above max guardrail raises ValueError."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
            "price_guardrails": {"min_price": 10, "max_price": 100},
        }):
            with pytest.raises(ValueError, match="price_outside_guardrails"):
                await publish_variant_price(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content={"recommended_price": 150},
                    product_id="123",
                    context={"variant_id": "var_456"},
                )

    @pytest.mark.asyncio
    async def test_raises_when_variant_id_missing(self):
        """Test that missing variant_id raises ValueError."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
        }):
            with pytest.raises(ValueError, match="variant_id and recommended_price required"):
                await publish_variant_price(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content={},
                    product_id="123",
                    context={},
                )

    @pytest.mark.asyncio
    async def test_passes_with_no_guardrails(self):
        """Test that price passes when no guardrails are configured."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
            "price_guardrails": None,
        }), patch("src.ecommerce.services.shopify_service.update_variant_price", new_callable=AsyncMock) as mock_update:

            await publish_variant_price(
                db=mock_db,
                shop="test.myshopify.com",
                content={"recommended_price": 9999.99},
                product_id="123",
                context={"variant_id": "var_456"},
            )

            mock_update.assert_called_once()


# =============================================================================
# Tests: publish_meta_post
# =============================================================================

class TestPublishMetaPost:
    """Tests for the publish_meta_post handler."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Test successful Meta post publish."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
            "meta_access_token": "EAA_token",
            "meta_page_id": "page_123",
        }), patch("src.agentic_core.tools.meta_service.MetaService") as MockMeta:
            mock_instance = MockMeta.return_value
            mock_instance.post_ad = AsyncMock(return_value=(True, "post_id_999"))

            await publish_meta_post(
                db=mock_db,
                shop="test.myshopify.com",
                content="Amazing new product! 🎉",
                product_id="123",
                context={},
            )

            mock_instance.post_ad.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_meta_credentials_missing(self):
        """Test that missing Meta credentials raises ValueError."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
            "meta_access_token": None,
            "meta_page_id": None,
        }):
            with pytest.raises(ValueError, match="meta_credentials_missing"):
                await publish_meta_post(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content="Test caption",
                    product_id="123",
                    context={},
                )

    @pytest.mark.asyncio
    async def test_raises_when_meta_post_fails(self):
        """Test that failed Meta post raises Exception."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
            "meta_access_token": "EAA_token",
            "meta_page_id": "page_123",
        }), patch("src.agentic_core.tools.meta_service.MetaService") as MockMeta:
            mock_instance = MockMeta.return_value
            mock_instance.post_ad = AsyncMock(return_value=(False, "Invalid token"))

            with pytest.raises(Exception, match="Meta post failed"):
                await publish_meta_post(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content="Test",
                    product_id="123",
                    context={},
                )

    @pytest.mark.asyncio
    async def test_passes_image_url_from_context(self):
        """Test that image_url is passed to MetaService from context."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
            "meta_access_token": "EAA_token",
            "meta_page_id": "page_123",
        }), patch("src.agentic_core.tools.meta_service.MetaService") as MockMeta:
            mock_instance = MockMeta.return_value
            mock_instance.post_ad = AsyncMock(return_value=(True, "post_99"))

            await publish_meta_post(
                db=mock_db,
                shop="test.myshopify.com",
                content="Test caption",
                product_id="123",
                context={"image_url": "https://cdn.shopify.com/product.jpg"},
            )

            call_kwargs = mock_instance.post_ad.call_args.kwargs
            assert call_kwargs["image_url"] == "https://cdn.shopify.com/product.jpg"


# =============================================================================
# Tests: publish_flow_campaign
# =============================================================================

class TestPublishFlowCampaign:
    """Tests for the publish_flow_campaign handler."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Test successful Shopify Flow trigger."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
        }), patch("src.ecommerce.services.shopify_service.trigger_flow_event", new_callable=AsyncMock) as mock_trigger:

            await publish_flow_campaign(
                db=mock_db,
                shop="test.myshopify.com",
                content="Campaign email body",
                product_id="123",
                context={},
            )

            mock_trigger.assert_called_once()
            call_kwargs = mock_trigger.call_args.kwargs
            assert call_kwargs["event_topic"] == "crossborder/seasonal-campaign"
            assert call_kwargs["payload"]["product_id"] == "123"

    @pytest.mark.asyncio
    async def test_raises_when_missing_credentials(self):
        """Test that missing credentials raises ValueError."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={}):
            with pytest.raises(ValueError, match="missing_credentials"):
                await publish_flow_campaign(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content="Test",
                    product_id="123",
                    context={},
                )


# =============================================================================
# Tests: publish_value_metafields
# =============================================================================

class TestPublishValueMetafields:
    """Tests for the publish_value_metafields handler."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Test successful value discovery metafield publish."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
        }), patch("src.ecommerce.services.shopify_service.save_product_metafields", new_callable=AsyncMock) as mock_save:

            await publish_value_metafields(
                db=mock_db,
                shop="test.myshopify.com",
                content='[{"name": "handcrafted", "confidence": 0.95}]',
                product_id="123",
                context={},
            )

            mock_save.assert_called_once()
            call_kwargs = mock_save.call_args.kwargs
            assert call_kwargs["product_id"] == "123"
            assert call_kwargs["metafields"][0]["key"] == "value_discovery"

    @pytest.mark.asyncio
    async def test_raises_when_missing_product_id(self):
        """Test that missing product_id raises ValueError."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
        }):
            with pytest.raises(ValueError, match="product_id required"):
                await publish_value_metafields(
                    db=mock_db,
                    shop="test.myshopify.com",
                    content="[]",
                    product_id=None,
                    context={},
                )

    @pytest.mark.asyncio
    async def test_handles_dict_content(self):
        """Test that dict content is JSON-serialized for metafield value."""
        mock_db = MagicMock()

        with patch("src.ecommerce.services.shopify_service.get_shop_credentials", return_value={
            "access_token": "shpat_test",
        }), patch("src.ecommerce.services.shopify_service.save_product_metafields", new_callable=AsyncMock) as mock_save:

            await publish_value_metafields(
                db=mock_db,
                shop="test.myshopify.com",
                content=[{"name": "artisan"}],
                product_id="123",
                context={},
            )

            # Content (list) should be JSON-serialized
            call_kwargs = mock_save.call_args.kwargs
            import json
            value = call_kwargs["metafields"][0]["value"]
            parsed = json.loads(value)
            assert parsed[0]["name"] == "artisan"

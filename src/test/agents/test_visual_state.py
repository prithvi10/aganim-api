"""
Unit tests for visual-related fields on ShopifyMissionState.

Covers:
  - visual_assets and visual_progress default values
  - to_dict serialization of visual fields
  - from_dict deserialization of visual fields
  - Roundtrip serialization
  - Coexistence with all other state fields
"""

import pytest

from src.ecommerce.state import MissionState


# =============================================================================
# Tests: Default values
# =============================================================================

class TestVisualStateDefaults:
    """Test visual fields have correct defaults."""

    def test_visual_assets_default_none(self):
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
        )
        assert state.visual_assets is None

    def test_visual_progress_default_none(self):
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
        )
        assert state.visual_progress is None


# =============================================================================
# Tests: to_dict
# =============================================================================

class TestVisualStateToDict:
    """Test to_dict serialization of visual fields."""

    def test_visual_assets_serialized(self):
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
        )
        state.visual_assets = {
            "refined_url": "https://r2.example.com/refined.png",
            "ad_url": "https://r2.example.com/ad.png",
            "hero_url": "https://r2.example.com/hero.png",
            "original_image_url": "https://cdn.shopify.com/product.jpg",
        }

        d = state.to_dict()
        assert d["visual_assets"] == state.visual_assets
        assert d["visual_assets"]["refined_url"] == "https://r2.example.com/refined.png"

    def test_visual_progress_serialized(self):
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
        )
        state.visual_progress = {"phase": "inpainting", "pct": 50, "label": "Working..."}

        d = state.to_dict()
        assert d["visual_progress"]["phase"] == "inpainting"
        assert d["visual_progress"]["pct"] == 50

    def test_none_visual_fields_serialized(self):
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )

        d = state.to_dict()
        assert d["visual_assets"] is None
        assert d["visual_progress"] is None


# =============================================================================
# Tests: from_dict
# =============================================================================

class TestVisualStateFromDict:
    """Test from_dict deserialization of visual fields."""

    def test_visual_assets_deserialized(self):
        data = {
            "product_id": "test",
            "shop_id": "test-shop",
            "plan_tier": "Pro",
            "raw_input": {},
            "visual_assets": {
                "refined_url": "https://r2/refined.png",
                "ad_url": None,
                "hero_url": "https://r2/hero.png",
            },
        }
        state = MissionState.from_dict(data)
        assert state.visual_assets["refined_url"] == "https://r2/refined.png"
        assert state.visual_assets["ad_url"] is None
        assert state.visual_assets["hero_url"] == "https://r2/hero.png"

    def test_visual_progress_deserialized(self):
        data = {
            "product_id": "test",
            "shop_id": "test-shop",
            "plan_tier": "Pro",
            "raw_input": {},
            "visual_progress": {"phase": "complete", "pct": 100, "label": "Done!"},
        }
        state = MissionState.from_dict(data)
        assert state.visual_progress["phase"] == "complete"
        assert state.visual_progress["pct"] == 100

    def test_missing_visual_fields_default_none(self):
        data = {
            "product_id": "test",
            "shop_id": "test-shop",
            "plan_tier": "Standard",
            "raw_input": {},
        }
        state = MissionState.from_dict(data)
        assert state.visual_assets is None
        assert state.visual_progress is None


# =============================================================================
# Tests: Roundtrip
# =============================================================================

class TestVisualStateRoundtrip:
    """Test roundtrip serialization of visual fields."""

    def test_full_visual_assets_roundtrip(self):
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
        )
        original.visual_assets = {
            "refined_url": "https://r2/refined.png",
            "ad_url": "https://r2/ad.png",
            "hero_url": "https://r2/hero.png",
            "original_image_url": "https://cdn.shopify.com/product.jpg",
        }
        original.visual_progress = {
            "phase": "complete",
            "pct": 100,
            "label": "Visual pipeline complete",
        }

        data = original.to_dict()
        restored = MissionState.from_dict(data)

        assert restored.visual_assets == original.visual_assets
        assert restored.visual_progress == original.visual_progress

    def test_none_visual_assets_roundtrip(self):
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )

        data = original.to_dict()
        restored = MissionState.from_dict(data)

        assert restored.visual_assets is None
        assert restored.visual_progress is None

    def test_visual_alongside_other_fields(self):
        """Test visual fields coexist with all other state fields."""
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={"title": "Test Product"},
            autonomous=True,
        )
        original.draft_content = "<p>Content</p>"
        original.seo_title = "SEO Title"
        original.current_agent_index = 4
        original.workflow_agents = [
            "RewriterAgent", "SEOAgent", "MarketingAgent",
            "PriceScoutAgent", "VisualAgent",
        ]
        original.visual_assets = {
            "refined_url": "https://r2/refined.png",
            "ad_url": "https://r2/ad.png",
            "hero_url": "https://r2/hero.png",
        }
        original.visual_progress = {
            "phase": "complete",
            "pct": 100,
            "label": "Done",
        }

        data = original.to_dict()
        restored = MissionState.from_dict(data)

        # Visual fields
        assert restored.visual_assets == original.visual_assets
        assert restored.visual_progress == original.visual_progress
        # Other fields
        assert restored.draft_content == original.draft_content
        assert restored.seo_title == original.seo_title
        assert restored.autonomous is True
        assert len(restored.workflow_agents) == 5
        assert restored.current_agent_index == 4

    def test_partial_visual_assets_roundtrip(self):
        """Test roundtrip with only some visual asset URLs set."""
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
        )
        original.visual_assets = {
            "refined_url": "https://r2/refined.png",
            "ad_url": None,
            "hero_url": None,
            "original_image_url": "https://cdn.shopify.com/img.jpg",
        }

        data = original.to_dict()
        restored = MissionState.from_dict(data)

        assert restored.visual_assets["refined_url"] == "https://r2/refined.png"
        assert restored.visual_assets["ad_url"] is None
        assert restored.visual_assets["hero_url"] is None

"""
Unit tests for Visual agent Pydantic schemas.

Covers:
  - VisualAsset: construction, field validation
  - VisualAssets: construction, to_dict, optional fields
  - VisualProgress: construction, pct bounds, required fields
"""

import pytest
from pydantic import ValidationError

from src.ecommerce.agents.visual.schemas import VisualAsset, VisualAssets, VisualProgress


# =============================================================================
# Tests: VisualAsset
# =============================================================================

class TestVisualAsset:
    """Test VisualAsset model."""

    def test_construction_minimal(self):
        asset = VisualAsset(asset_type="refined", url="https://r2.example.com/img.png")
        assert asset.asset_type == "refined"
        assert asset.url == "https://r2.example.com/img.png"
        assert asset.content_type == "image/png"
        assert asset.width is None
        assert asset.height is None

    def test_construction_full(self):
        asset = VisualAsset(
            asset_type="hero",
            url="https://r2.example.com/hero.png",
            width=1920,
            height=1080,
            content_type="image/jpeg",
        )
        assert asset.width == 1920
        assert asset.height == 1080
        assert asset.content_type == "image/jpeg"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            VisualAsset()

    def test_missing_url(self):
        with pytest.raises(ValidationError):
            VisualAsset(asset_type="ad")

    def test_missing_asset_type(self):
        with pytest.raises(ValidationError):
            VisualAsset(url="https://example.com/img.png")


# =============================================================================
# Tests: VisualAssets
# =============================================================================

class TestVisualAssets:
    """Test VisualAssets model."""

    def test_empty_construction(self):
        assets = VisualAssets()
        assert assets.refined_url is None
        assert assets.ad_url is None
        assert assets.hero_url is None
        assert assets.original_image_url is None

    def test_full_construction(self):
        assets = VisualAssets(
            refined_url="https://r2.example.com/refined.png",
            ad_url="https://r2.example.com/ad.png",
            hero_url="https://r2.example.com/hero.png",
            original_image_url="https://cdn.shopify.com/product.jpg",
        )
        assert assets.refined_url == "https://r2.example.com/refined.png"
        assert assets.ad_url == "https://r2.example.com/ad.png"
        assert assets.hero_url == "https://r2.example.com/hero.png"

    def test_to_dict(self):
        assets = VisualAssets(
            refined_url="https://r2.example.com/refined.png",
        )
        d = assets.to_dict()
        assert isinstance(d, dict)
        assert d["refined_url"] == "https://r2.example.com/refined.png"
        assert d["ad_url"] is None
        assert d["hero_url"] is None

    def test_partial_construction(self):
        """Only refined, no ad or hero."""
        assets = VisualAssets(refined_url="https://r2.example.com/refined.png")
        assert assets.refined_url == "https://r2.example.com/refined.png"
        assert assets.ad_url is None


# =============================================================================
# Tests: VisualProgress
# =============================================================================

class TestVisualProgress:
    """Test VisualProgress model."""

    def test_valid_progress(self):
        prog = VisualProgress(phase="masking", pct=25, label="Isolating product...")
        assert prog.phase == "masking"
        assert prog.pct == 25
        assert prog.label == "Isolating product..."

    def test_zero_percent(self):
        prog = VisualProgress(phase="error", pct=0, label="Pipeline error")
        assert prog.pct == 0

    def test_hundred_percent(self):
        prog = VisualProgress(phase="complete", pct=100, label="Done")
        assert prog.pct == 100

    def test_negative_pct_raises(self):
        with pytest.raises(ValidationError):
            VisualProgress(phase="error", pct=-1, label="Bad")

    def test_pct_over_100_raises(self):
        with pytest.raises(ValidationError):
            VisualProgress(phase="error", pct=101, label="Bad")

    def test_missing_phase_raises(self):
        with pytest.raises(ValidationError):
            VisualProgress(pct=50, label="Working...")

    def test_missing_label_raises(self):
        with pytest.raises(ValidationError):
            VisualProgress(phase="masking", pct=50)

    def test_missing_pct_raises(self):
        with pytest.raises(ValidationError):
            VisualProgress(phase="masking", label="Working...")

    def test_all_phases_valid(self):
        """Test all expected phase values."""
        phases = ["masking", "inpainting", "ad_generation", "outpainting", "uploading", "complete"]
        for phase in phases:
            prog = VisualProgress(phase=phase, pct=50, label=f"At {phase}")
            assert prog.phase == phase

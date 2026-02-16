"""
Pydantic schemas for the VisualAgent pipeline.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class VisualAsset(BaseModel):
    """A single generated visual asset."""

    asset_type: str = Field(
        ...,
        description="Type of asset: 'refined', 'ad', or 'hero'",
    )
    url: str = Field(..., description="Public URL or local path of the asset")
    width: Optional[int] = None
    height: Optional[int] = None
    content_type: str = "image/png"


class VisualAssets(BaseModel):
    """Collection of all visual assets produced by a single pipeline run."""

    refined_url: Optional[str] = Field(
        None,
        description="URL of the refined product image (brand-aligned background)",
    )
    ad_url: Optional[str] = Field(
        None,
        description="URL of the marketing ad with typography",
    )
    hero_url: Optional[str] = Field(
        None,
        description="URL of the 16:9 hero banner",
    )
    original_image_url: Optional[str] = Field(
        None,
        description="Original product image URL used as input",
    )

    def to_dict(self) -> Dict[str, Optional[str]]:
        return self.model_dump()


class VisualProgress(BaseModel):
    """Progress update emitted during visual generation for SSE streaming."""

    phase: str = Field(
        ...,
        description=(
            "Current phase: masking, inpainting, ad_generation, "
            "outpainting, uploading, complete"
        ),
    )
    pct: int = Field(..., ge=0, le=100, description="Progress percentage 0-100")
    label: str = Field(..., description="Human-readable status label for the UI")

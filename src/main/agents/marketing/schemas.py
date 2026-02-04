"""
Marketing Agent Pydantic Schemas

Structured output models for the MarketingAgent including social hooks
and seasonal campaigns.

Note: SEO-related schemas have been moved to the SEOAgent (src/main/agents/seo/schemas.py).
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Social Hook Schemas
# =============================================================================

class SocialHook(BaseModel):
    """Social media hook for Instagram/TikTok marketing."""
    
    type: str = Field(
        description="Hook type: Aesthetic, Educational, or Viral"
    )
    caption: str = Field(
        description="Social media caption (<= 220 chars)"
    )
    hashtags: List[str] = Field(
        default_factory=list,
        description="8-12 relevant hashtags"
    )
    overlay: Optional[str] = Field(
        default=None,
        description="Text overlay suggestion for Reels (<= 28 chars)"
    )
    copy_text: str = Field(
        default="",
        description="Full copyable text with caption + hashtags"
    )


class SeasonalCampaign(BaseModel):
    """Seasonal campaign data for holiday marketing."""
    
    holiday_name: str = Field(
        description="Name of the upcoming holiday"
    )
    holiday_date: str = Field(
        description="ISO date of the holiday"
    )
    days_until: int = Field(
        description="Days until the holiday"
    )
    campaign_title: str = Field(
        description="Suggested campaign title"
    )
    discount_code: str = Field(
        description="Suggested discount code"
    )
    caption: Optional[str] = Field(
        default=None,
        description="Seasonal caption if generated"
    )


# =============================================================================
# Full Marketing Output (Social Hooks only)
# =============================================================================

class MarketingOutput(BaseModel):
    """Full structured output from MarketingAgent."""
    
    # Social hooks
    social_hooks: List[SocialHook] = Field(
        default_factory=list,
        description="Generated social media hooks/captions"
    )
    
    # Overlay suggestions
    overlay_suggestions: List[str] = Field(
        default_factory=list,
        description="Suggested text overlays for Reels"
    )
    
    # Optional seasonal campaign
    seasonal_campaign: Optional[SeasonalCampaign] = Field(
        default=None,
        description="Seasonal campaign data if applicable"
    )

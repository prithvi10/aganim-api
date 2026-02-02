"""
Marketing Agent Pydantic Schemas

Structured output models for the MarketingAgent including SEO, CTR checking,
SERP competitor insights, and social hooks.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# =============================================================================
# SEO Schemas
# =============================================================================

class SEOInsights(BaseModel):
    """LSI keyword and search intent analysis from SERP data."""
    
    lsi_keywords_used: List[str] = Field(
        default_factory=list,
        description="5-8 high-density LSI keywords from top competitors"
    )
    search_intent: str = Field(
        default="Transactional",
        description="Primary search intent: Transactional or Informational"
    )
    competitive_edge: str = Field(
        default="",
        description="One unique Japanese/product detail competitors missed"
    )


class CompetitiveEdge(BaseModel):
    """Differentiation analysis based on product facts."""
    
    model_config = {"populate_by_name": True}
    
    headline: str = Field(
        default="",
        description="Short differentiation headline in target language"
    )
    copy_text: str = Field(
        default="",
        alias="copy",
        description="1-2 sentences describing edge using only facts from description"
    )


class BuyerIntent(BaseModel):
    """Buyer intent alignment strategy."""
    
    strategy: List[str] = Field(
        default_factory=list,
        description="3-6 bullets describing how to align copy to buyer intent"
    )


class SEORecommendations(BaseModel):
    """Actionable SEO improvement suggestions."""
    
    competitive_edge: CompetitiveEdge = Field(
        default_factory=CompetitiveEdge,
        description="Differentiation analysis"
    )
    buyer_intent: BuyerIntent = Field(
        default_factory=BuyerIntent,
        description="Buyer intent alignment strategy"
    )


# =============================================================================
# CTR / PST Schemas
# =============================================================================

class CTRCheck(BaseModel):
    """PST (Pain-Solution-Trust) formula validation for CTR optimization."""
    
    pain_present: bool = Field(
        default=False,
        description="Does the description address a pain point or desire?"
    )
    solution_present: bool = Field(
        default=False,
        description="Does it present a concrete benefit with a key spec?"
    )
    trust_present: bool = Field(
        default=False,
        description="Does it include trust cues (brand, provenance, shipping)?"
    )
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall CTR score from 0.0 to 1.0"
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description="Actionable suggestions to improve CTR"
    )


# =============================================================================
# SERP Competitor Schemas
# =============================================================================

class SerpCompetitor(BaseModel):
    """Competitor data from Google SERP."""
    
    title: str = Field(
        description="Competitor page title"
    )
    snippet: str = Field(
        description="Competitor meta description/snippet"
    )
    link: str = Field(
        description="Competitor URL"
    )
    position: int = Field(
        ge=1,
        le=10,
        description="SERP position (1-10)"
    )


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
# Full Marketing Output
# =============================================================================

class MarketingOutput(BaseModel):
    """Full structured output from MarketingAgent."""
    
    # Core SEO fields
    seo_title: str = Field(
        default="",
        description="SEO-optimized meta title (<= 70 characters)"
    )
    seo_description: str = Field(
        default="",
        description="SEO-optimized meta description (<= 160 characters, PST formula)"
    )
    seo_alt_text: str = Field(
        default="",
        description="Descriptive alt-tag for main product image"
    )
    
    # SEO Insights from SERP analysis
    seo_insights: SEOInsights = Field(
        default_factory=SEOInsights,
        description="LSI keywords, search intent, competitive edge"
    )
    
    # SEO Recommendations
    seo_recommendations: SEORecommendations = Field(
        default_factory=SEORecommendations,
        description="Competitive edge and buyer intent analysis"
    )
    
    # CTR Check
    ctr_check: CTRCheck = Field(
        default_factory=CTRCheck,
        description="PST formula validation"
    )

"""
SEO Agent Pydantic Schemas

Structured output models for the SEOAgent including SEO metadata,
CTR checking, and SERP competitor insights.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# SEO Insights Schema
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


# =============================================================================
# CTR / PST Schema
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
# SERP Competitor Schema
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
# Full SEO Output
# =============================================================================

class SEOOutput(BaseModel):
    """Full structured output from SEOAgent."""
    
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
    
    # CTR Check
    ctr_check: CTRCheck = Field(
        default_factory=CTRCheck,
        description="PST formula validation"
    )
    
    # SERP competitors
    serp_competitors: List[SerpCompetitor] = Field(
        default_factory=list,
        description="Top 3 Google SERP competitors"
    )

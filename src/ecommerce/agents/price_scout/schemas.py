"""
PriceScout Agent Pydantic Schemas

Structured output models for the PriceScoutAgent.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


# ==============================================================================
# Shopping Competitor Schema (from Google Shopping API)
# ==============================================================================

class ShoppingCompetitor(BaseModel):
    """Structured competitor from Google Shopping."""
    
    title: str = Field(description="Product title from shopping result")
    price: str = Field(description="Display price string (e.g., '$45.00')")
    extracted_price: float = Field(description="Numeric price value for calculations")
    source: str = Field(description="Merchant name (e.g., 'Amazon', 'Etsy')")
    link: str = Field(description="Product URL")
    thumbnail: Optional[str] = Field(default=None, description="Image URL")
    shipping: Optional[str] = Field(default=None, description="Shipping information")
    is_relevant: bool = Field(default=True, description="Whether this is a true comparable (set by semantic filter)")


# ==============================================================================
# Semantic Filtering Schemas
# ==============================================================================

class FilteredCompetitorsResponse(BaseModel):
    """LLM response for semantic filtering of competitors."""
    
    valid_competitor_indices: List[int] = Field(
        description="0-based indices of competitors that are true comparables to keep"
    )
    reasoning: str = Field(
        description="Brief explanation of filtering decisions"
    )


# ==============================================================================
# Market Analysis Schema
# ==============================================================================

class MarketAnalysis(BaseModel):
    """Calculated market metrics from filtered competitors."""
    
    min_price: float = Field(description="Lowest price among filtered competitors")
    max_price: float = Field(description="Highest price among filtered competitors")
    average_price: float = Field(description="Mean price of filtered competitors")
    median_price: float = Field(description="Median price of filtered competitors")
    competitor_count: int = Field(description="Number of valid competitors after filtering")


# ==============================================================================
# Pricing Analysis Schema (Updated)
# ==============================================================================

class PricingAnalysis(BaseModel):
    """
    Response format for PriceScoutAgent.
    
    Analyzes competitor pricing and recommends optimal price point.
    Now includes filtered competitors and market analysis.
    """
    
    competitor_avg_price: float = Field(
        description="Average price among filtered competitors"
    )
    recommended_price: float = Field(
        description="Recommended price for the product"
    )
    price_position: str = Field(
        description="Market position: premium, competitive, budget"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the recommendation (0-1)"
    )
    reasoning: str = Field(
        description="Explanation of the pricing recommendation"
    )
    competitor_count: Optional[int] = Field(
        default=None,
        description="Number of competitors analyzed"
    )


# ==============================================================================
# Legacy Schema (Backward Compatibility)
# ==============================================================================

class CompetitorData(BaseModel):
    """
    Structured competitor data from SERP results.
    
    NOTE: This is a legacy schema from organic search.
    Use ShoppingCompetitor for Google Shopping results.
    """
    
    title: str = Field(description="Product title from search result")
    snippet: str = Field(description="Description snippet")
    link: str = Field(description="Product URL")
    extracted_price: Optional[float] = Field(
        default=None,
        description="Price extracted from title/snippet if found"
    )

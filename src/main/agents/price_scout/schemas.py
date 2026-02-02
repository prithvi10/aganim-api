"""
PriceScout Agent Pydantic Schemas

Structured output models for the PriceScoutAgent.
"""

from typing import Optional
from pydantic import BaseModel, Field


class PricingAnalysis(BaseModel):
    """
    Response format for PriceScoutAgent.
    
    Analyzes competitor pricing and recommends optimal price point.
    """
    
    competitor_avg_price: float = Field(
        description="Average price among competitors"
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


class CompetitorData(BaseModel):
    """
    Structured competitor data from SERP results.
    """
    
    title: str = Field(description="Product title from search result")
    snippet: str = Field(description="Description snippet")
    link: str = Field(description="Product URL")
    extracted_price: Optional[float] = Field(
        default=None,
        description="Price extracted from title/snippet if found"
    )

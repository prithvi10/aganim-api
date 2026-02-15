"""
Rewriter Agent Pydantic Schemas

Structured output models for the RewriterAgent.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class RewriterOutput(BaseModel):
    """
    Structured output for RewriterAgent.
    
    Contains the content pieces generated for a product.
    
    Note: SEO fields (seo_title, seo_description, seo_alt_text) are handled
    by the dedicated SEOAgent and are not part of the Rewriter output.
    """
    
    title: str = Field(
        description="Optimized product title"
    )
    description: str = Field(
        description="Optimized product description (HTML)"
    )
    discovered_values: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Discovered value propositions (Japanese craftsmanship values)"
    )


class ValueDiscovery(BaseModel):
    """
    Discovered value proposition from product content.
    
    Used to identify Japanese craftsmanship values like
    Regional Pedigree, Artisan Master, etc.
    """
    
    category: str = Field(
        description="Value category: Regional Pedigree, Tactile & Sensory, Time-as-Luxury, Artisan Master"
    )
    evidence: str = Field(
        description="Evidence from the product text supporting this value"
    )
    explanation: str = Field(
        description="Why this qualifies as the category"
    )
    suggested_footer: str = Field(
        description="Suggested footer text highlighting this value"
    )


class RewritingPlan(BaseModel):
    """
    Plan created by advanced RewriterAgent during LLM reasoning.
    
    Only used when requires_llm_reasoning = True (Pro tier).
    """
    
    tone: str = Field(
        description="Recommended tone: professional, casual, luxury, etc."
    )
    style: str = Field(
        description="Writing style to use"
    )
    key_points: List[str] = Field(
        default_factory=list,
        description="Key points to emphasize in the copy"
    )
    target_audience: Optional[str] = Field(
        default=None,
        description="Inferred target audience"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in this plan"
    )
    reasoning: str = Field(
        description="Why this approach was chosen"
    )
    steps: List[str] = Field(
        default_factory=lambda: ["generate_content"],
        description="Steps to execute"
    )

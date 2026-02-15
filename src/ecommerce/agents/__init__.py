"""
Ecommerce domain agents - Shopify-specific agent subclasses.
"""

from .rewriter import RewriterAgent, RewriterOutput
from .seo import SEOAgent, SEOInsights, CTRCheck, SerpCompetitor, SEOOutput
from .marketing import (
    MarketingAgent,
    MarketingOutput,
    SocialHook,
    SeasonalCampaign,
)
from .price_scout import PriceScoutAgent, PricingAnalysis
from .compliance import ComplianceAgent, ComplianceCheck

# Backward compatibility aliases
CopywriterAgent = RewriterAgent
CopywriterOutput = RewriterOutput

__all__ = [
    "RewriterAgent",
    "RewriterOutput",
    "CopywriterAgent",
    "CopywriterOutput",
    "SEOAgent",
    "SEOOutput",
    "SEOInsights",
    "CTRCheck",
    "SerpCompetitor",
    "MarketingAgent",
    "MarketingOutput",
    "SocialHook",
    "SeasonalCampaign",
    "PriceScoutAgent",
    "PricingAnalysis",
    "ComplianceAgent",
    "ComplianceCheck",
]

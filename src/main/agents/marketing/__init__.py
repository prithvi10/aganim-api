"""
Marketing Agent Package

Exports the MarketingAgent and related schemas for SEO, CTR checking,
SERP competitor insights, and social media marketing.
"""

from .agent import MarketingAgent
from .schemas import (
    MarketingOutput,
    SEOInsights,
    SEORecommendations,
    CompetitiveEdge,
    BuyerIntent,
    CTRCheck,
    SerpCompetitor,
    SocialHook,
)

__all__ = [
    "MarketingAgent",
    "MarketingOutput",
    "SEOInsights",
    "SEORecommendations",
    "CompetitiveEdge",
    "BuyerIntent",
    "CTRCheck",
    "SerpCompetitor",
    "SocialHook",
]

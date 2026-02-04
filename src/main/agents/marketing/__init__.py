"""
Marketing Agent Package

Exports the MarketingAgent and related schemas for social media marketing.

Note: SEO functionality has been moved to the dedicated SEOAgent package.
"""

from .agent import MarketingAgent
from .schemas import (
    MarketingOutput,
    SocialHook,
    SeasonalCampaign,
)

__all__ = [
    "MarketingAgent",
    "MarketingOutput",
    "SocialHook",
    "SeasonalCampaign",
]

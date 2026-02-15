"""
SEO Agent Module

Handles all SEO-related functionality:
- SERP competitor analysis
- SEO title/description/alt-text generation
- CTR/PST formula validation
"""

from .agent import SEOAgent
from .schemas import (
    SEOInsights,
    CTRCheck,
    SerpCompetitor,
    SEOOutput,
)

__all__ = [
    "SEOAgent",
    "SEOInsights",
    "CTRCheck",
    "SerpCompetitor",
    "SEOOutput",
]

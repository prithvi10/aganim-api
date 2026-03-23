"""
Regression Test Modules (REAL API CALLS)

This package contains test modules that make REAL API calls to:
- OpenAI (LLM generation)
- SERP API (competitor analysis)

Required Environment Variables:
- OPENAI_API_KEY: OpenAI API key (required)
- SERP_API_KEY: SERP API key (optional)

Modules:
- agent_output_tests: Validates agent outputs (discovered_values, compliance flags)
- seo_feature_tests: Validates SEO generation (title, description, alt-text, CTR)
- spec_table_tests: Validates specification and dimension table generation
- rag_brand_soul_tests: Validates RAG brand context injection
- tier_feature_tests: Validates tier-specific agent coverage

Usage:
    # Run all tests
    python scripts/regression_test_suite.py
    
    # Run specific module
    python scripts/regression_test_suite.py --module agents
"""

# Lazy imports to avoid circular dependencies
__all__ = [
    "AgentOutputTests",
    "SEOFeatureTests",
    "SpecTableTests",
    "RAGBrandSoulTests",
    "TierFeatureTests",
    "BrandIngestTests",
]


def __getattr__(name: str):
    """Lazy load test classes."""
    if name == "AgentOutputTests":
        from .agent_output_tests import AgentOutputTests
        return AgentOutputTests
    elif name == "SEOFeatureTests":
        from .seo_feature_tests import SEOFeatureTests
        return SEOFeatureTests
    elif name == "SpecTableTests":
        from .spec_table_tests import SpecTableTests
        return SpecTableTests
    elif name == "RAGBrandSoulTests":
        from .rag_brand_soul_tests import RAGBrandSoulTests
        return RAGBrandSoulTests
    elif name == "TierFeatureTests":
        from .tier_feature_tests import TierFeatureTests
        return TierFeatureTests
    elif name == "BrandIngestTests":
        from .brand_ingest_tests import BrandIngestTests
        return BrandIngestTests
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""
Services Layer - Clean abstraction between Agents and external APIs/business logic.

Each service is a class with well-defined async methods. Agents receive services
via dependency injection through a ServiceRegistry.

This module consolidates:
- LLMService: OpenAI API interactions (new agentic style)  [from agentic_core]
- SerpService: Search engine results                       [from agentic_core]
- RAGService: Brand context retrieval                      [from agentic_core]
- OpenAIService: Legacy OpenAI wrapper (backward compatibility)
- FairUseService: Usage tracking and cost management
- OnboardingService: User onboarding workflow
- ShopifyService: Shopify API interactions
- BrandIngestService: Brand context ingestion
- ValueDiscoveryService: Evidence discovery engine
"""

from .registry import ServiceRegistry

# Agentic-core services (re-exported for convenience)
from src.agentic_core.llm.llm_service import LLMService
from src.agentic_core.llm.usage import LLMUsage, AccumulatedUsage
from src.agentic_core.tools.serp_service import SerpService, SerpResult, fetch_top_results
from src.agentic_core.rag.rag_service import RAGService, get_brand_context

# Legacy/Business services
from .openai_legacy_service import OpenAIService
from .fair_use_service import (
    get_base_model_for_shop,
    get_effective_model,
    record_cost_from_usage,
    record_token_usage,
    is_fair_use_violated,
    should_degrade_model,
    should_throttle_for_cycle,
    notify_fair_use_if_needed,
)
from .onboarding_service import onboard_user
from .shopify_service import (
    create_shopify_translation,
    save_product_content_with_locale,
    save_product_metafields,
)
from .brand_ingest_service import (
    ingest_brand_context,
    scrape_urls,
    extract_file_text,
)
from .value_discovery_service import ValueDiscoveryService

__all__ = [
    # Core agentic services
    "ServiceRegistry",
    "LLMService",
    "LLMUsage",
    "AccumulatedUsage",
    "SerpService",
    "SerpResult",
    "fetch_top_results",
    "RAGService",
    "get_brand_context",
    # Legacy/Business services
    "OpenAIService",
    # Fair use
    "get_base_model_for_shop",
    "get_effective_model",
    "record_cost_from_usage",
    "record_token_usage",
    "is_fair_use_violated",
    "should_degrade_model",
    "should_throttle_for_cycle",
    "notify_fair_use_if_needed",
    # Onboarding
    "onboard_user",
    # Shopify
    "create_shopify_translation",
    "save_product_content_with_locale",
    "save_product_metafields",
    # Brand ingest
    "ingest_brand_context",
    "scrape_urls",
    "extract_file_text",
    # Value discovery
    "ValueDiscoveryService",
]

"""
Generic AI / agentic-core configuration.

Domain-specific settings (Shopify UI, Fair-Use caps, locale maps, glossaries)
live in ``src/ecommerce/config/shopify_config.py``.
"""

import os

# Prompts are defined in config/prompts.py. Re-export here for backward compatibility.
from src.shared.config.prompts import SYSTEM_PROMPT, TONE_PROMPTS, VALUE_DISCOVERY_PROMPT  # noqa: F401

# OpenAI Configuration
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.5
# IMPORTANT: 700 tokens was causing truncated JSON for long, detail-heavy descriptions
# (especially when Shop/Shipping/Returns sections are present), which dropped SEO + discovered_values.
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "2200"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))

# Defaults
DEFAULT_PRODUCT_CATEGORY = "General Goods"

# ------------------------------------------------------------------------------
# SERP API (Standard/Pro optimization enrichment)
# ------------------------------------------------------------------------------
SERP_API_KEY = os.getenv("SERP_API_KEY", "").strip()
SERP_API_URL = os.getenv("SERP_API_URL", "https://serpapi.com/search").strip()

# Strategy: Allow bursts, but cap long-term usage
PRODUCTION_RATE_LIMIT_CONFIG = [
    {"limit": 60,   "window": 60},    # Burst: 1 request/sec (average)
    {"limit": 1000, "window": 3600},  # Hourly: ~1000 per hour
    {"limit": 5000, "window": 86400}, # Daily:  ~5000 per day
]
# Strategy: Very low limits so you can trigger 429s easily
LOCAL_RATE_LIMIT_CONFIG = [
    {"limit": 5,  "window": 10},   # Burst: Max 5 requests per 10 seconds
    {"limit": 20, "window": 60},   # Sustained: Max 20 requests per minute
]

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shopify_translator")

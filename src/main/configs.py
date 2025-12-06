import os

# OpenAI Configuration
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.7
OPENAI_MAX_TOKENS = 500

# Defaults
DEFAULT_PRODUCT_CATEGORY = "General Goods"

# Prompts
SYSTEM_PROMPT = """
You are an expert American Direct-Response Copywriter.
Your goal is to take a factual Japanese product description and rewrite it 
into compelling, benefit-driven English marketing copy for a US Shopify store.

RULES:
- Tone: Sophisticated, warm, storytelling.
- Structure: 
  1. Catchy Headline (Under 10 words)
  2. The Story (Evoke emotion/origin)
  3. Key Features (Converted to Benefits)
  4. Care Instructions (If mentioned, make them friendly)
- NO "Japanglish" (awkward phrasing).
- NO made-up facts. Only use the info provided, but dramatize the value.
"""
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


import os

# OpenAI Configuration
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.7
OPENAI_MAX_TOKENS = 500

# Defaults
DEFAULT_PRODUCT_CATEGORY = "General Goods"

# Prompts
SYSTEM_PROMPT = """You are an expert American Direct-Response Copywriter.

Your primary goal is to take a factual Japanese product description and rewrite it 
into clear, benefit-driven English marketing copy for a US Shopify store.

CRITICAL CONSTRAINTS:
1. FIDELITY: Maintain strict 1:1 fidelity to all unique factual claims (e.g., materials, dimensions, specific filter types). The copy must feel like an authentic, refined translation.
2. LENGTH LIMIT: Total output MUST NOT exceed 200 words. (Under 150 words preferred for optimal reading.)
3. NO "Japanglish" (awkward phrasing).
4. NO made-up facts. Only use the info provided.

STRUCTURE:
1. Catchy Headline (Under 8 words)
2. Origin & Intent (Briefly state provenance and primary use. Maximum 3 sentences.)
3. Key Features (Convert features to consumer benefits, using bullet points.)
4. Care Instructions (If provided, translate clearly and in a friendly tone.)
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

# CORS Configuration
ALLOWED_ORIGINS = [
    "http://localhost:3000",      # Local React/Frontend
    "http://localhost:8000",      # Local API/Swagger UI
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]

# Add deployed URL from env if available
DEPLOYED_APP_URL = os.getenv("DEPLOYED_APP_URL")
if DEPLOYED_APP_URL:
    ALLOWED_ORIGINS.append(DEPLOYED_APP_URL)

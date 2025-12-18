import os

# OpenAI Configuration
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.5
OPENAI_MAX_TOKENS = 500

# Defaults
DEFAULT_PRODUCT_CATEGORY = "General Goods"

# Prompts
SYSTEM_PROMPT = """You are a Senior US E-commerce Growth Consultant. 

### PRIMARY GOAL:
Take a factual Japanese product description and rewrite it into clear, benefit-driven English marketing copy for a high-end US Shopify store. 

### AUTONOMOUS REASONING PROCESS (Perform Silently):
1. ANALYSIS: Identify materials, era, and unique craftsmanship from the Japanese data.
2. CATEGORIZATION: Define an appropriate premium US boutique category (e.g., Heritage Home, Artisan Fashion).
3. STRATEGY: Select a tone (e.g., Storytelling, Minimalist, or Technical) based on the category.
4. GENERATION: Produce the final JSON.

### CRITICAL CONSTRAINTS:
- INTERNAL REASONING: Perform steps 1-3 internally. Return ONLY the final JSON object.
- FIDELITY: Maintain 1:1 factual accuracy for dimensions, materials, and unique claims.
- STYLE: No "Japanglish." Total text must be under 150 words for optimal scannability.
- FORMAT: Return a valid JSON object with:
  - "title": Catchy headline (<8 words).
  - "description": Valid HTML (Use <h3> for headers, <ul>/<li> for lists, <p> for paragraphs). No <html>/<body> tags.

### JSON STRUCTURE:
{
  "title": "Headline",
  "description": "<h3>Header</h3><ul><li>Feature</li></ul><p>Benefit-driven copy...</p>"
}
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

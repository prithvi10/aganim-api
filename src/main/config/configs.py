import os

# OpenAI Configuration
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.5
OPENAI_MAX_TOKENS = 700

# Defaults
DEFAULT_PRODUCT_CATEGORY = "General Goods"

# Prompts
SYSTEM_PROMPT = """You are a Senior E-commerce Growth Copywriter.

### PRIMARY GOAL:
Transform a factual Japanese product description into localized, benefit-driven marketing copy for the specified TARGET market.

### AUTONOMOUS REASONING (Perform Silently):
1) Analyze the source facts (materials, dimensions, craftsmanship, usage).
2) Categorize: Define an appropriate premium boutique category for the TARGET market (e.g., Heritage Home, Artisan Fashion, Luxury Tech).
3) Strategy: Select a tone based on the category and market persona (e.g., Storytelling, Minimalist, Technical).
4) Adapt tone and triggers to the MARKET persona (see injected context).
5) Generate localized copy in the TARGET LANGUAGE only.

### CRITICAL CONSTRAINTS:
- Fidelity: 1:1 accuracy on factual claims; no invented details.
- Style: Avoid awkward "Japanglish". Keep total under ~150 words.
- Output Language: Write BOTH "title" and "description" in the TARGET LANGUAGE provided.
- Formatting: Return valid JSON with "title" (<8 words) and "description" (premium, well-structured HTML wrapped in <div class="ai-generated-description">). Do NOT include <html>/<body> tags.

### JSON STRUCTURE:
{
  "title": "Headline",
  "description": "<div class=\"ai-generated-description\"><h2>Header</h2><h4>Subheader</h4><ul><li>Feature</li></ul><table><tr><th>Size</th><td>...</td></tr><tr><th>Care</th><td>...</td></tr><tr><th>Tailoring</th><td>...</td></tr><tr><th>Includes</th><td>...</td></tr></table><p>Benefit-driven copy...</p></div>"
}

### LOCALIZATION GUIDANCE (DYNAMIC, WILL BE INJECTED):
- TARGET LANGUAGE: <injected at runtime>
- MARKET PERSONA: <injected at runtime>
- Use local idioms, tone, and market-specific triggers (e.g., CP値/CP ratio for Taiwan).
- Do not output English or Japanese unless they are the target language.

### ARCHITECTURAL RULES:
1. Preserve divisions: If source text has separate blocks (Taste, How to use, Specs), keep them distinct. Output separate <h3> blocks for each section label.
2. Visual hierarchy: <h2> (overall heading) optional, <h3> for section headers, <h4> for subheaders; use <hr /> between major logical sections.
3. Data representation: Use <table> for numeric or step-by-step data. Specs: [Attribute, Value]. Prep: [Step, Detail] or [Ingredient, Amount]. Required rows: Size, Care, Tailoring, Includes.
4. Sensory scales: For taste/strength, include visual indicators (e.g., Strength: ●●●○○ Rich).
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
    # Shopify Admin (Admin Action extensions run with this origin)
    "https://admin.shopify.com",
    # Shopify-hosted extensions origin (Admin UI Extensions)
    "https://extensions.shopifycdn.com",
]

# Add deployed URL from env if available
DEPLOYED_APP_URL = os.getenv("DEPLOYED_APP_URL")
if DEPLOYED_APP_URL:
    ALLOWED_ORIGINS.append(DEPLOYED_APP_URL)

# UI Frontend URL (for redirects)
SHOPIFY_UI_URL = os.getenv("SHOPIFY_UI_URL", "https://shopify-translator-ui.onrender.com")

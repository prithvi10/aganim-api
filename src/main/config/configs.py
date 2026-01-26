import os

# Prompts are defined in config/prompts.py. Re-export here for backward compatibility.
from src.main.config.prompts import SYSTEM_PROMPT, TONE_PROMPTS, VALUE_DISCOVERY_PROMPT  # noqa: F401

# OpenAI Configuration
OPENAI_MODEL = "gpt-4o-mini"
# Pro-only model (may be throttled down by Fair Use Monitoring)
# NOTE: This codebase uses `chat.completions` in `OpenAIService`. Some newer models
# (e.g., certain GPT-5 variants) may only be supported via the Responses API, which
# would cause 404s. Default to a chat-compatible model unless explicitly overridden.
OPENAI_MODEL_PRO = os.getenv("OPENAI_MODEL_PRO", "gpt-4o-mini") #Todo: Update before Go-Live
# Model used when Fair Use throttle is active for a shop
OPENAI_MODEL_DEGRADED = os.getenv("OPENAI_MODEL_DEGRADED", "gpt-4o-mini")
OPENAI_TEMPERATURE = 0.5
# IMPORTANT: 700 tokens was causing truncated JSON for long, detail-heavy descriptions
# (especially when Shop/Shipping/Returns sections are present), which dropped SEO + discovered_values.
OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "2200"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))

# ------------------------------------------------------------------------------
# Internal Fair Use Monitoring (never shown to merchants)
# ------------------------------------------------------------------------------
FAIR_USE_COST_CAP = float(os.getenv("FAIR_USE_COST_CAP", "150.0"))
# Default pricing: only output tokens are costed at $10 / 1M (per your spec).
# If you want full input/output/reasoning pricing, set these env vars.
FAIR_USE_USD_PER_1M_INPUT = float(os.getenv("FAIR_USE_USD_PER_1M_INPUT", "0"))
FAIR_USE_USD_PER_1M_OUTPUT = float(os.getenv("FAIR_USE_USD_PER_1M_OUTPUT", "10"))
FAIR_USE_USD_PER_1M_REASONING = float(os.getenv("FAIR_USE_USD_PER_1M_REASONING", "0"))

# ------------------------------------------------------------------------------
# Pricing / Launch campaign flags (used by UI; never shown as "limits" to merchants)
# ------------------------------------------------------------------------------
PROMO_PRICING_ENABLED = str(os.getenv("PROMO_PRICING_ENABLED", "false")).strip().lower() in (
    "1",
    "true",
    "yes",
    "y",
    "on",
)

# Defaults
DEFAULT_PRODUCT_CATEGORY = "General Goods"

# ------------------------------------------------------------------------------
# SERP API (Standard/Pro optimization enrichment)
# ------------------------------------------------------------------------------
SERP_API_KEY = os.getenv("SERP_API_KEY", "").strip()
SERP_API_URL = os.getenv("SERP_API_URL", "https://serpapi.com/search").strip()

# Prompts moved to config/prompts.py (re-exported at top of this file).

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

# ==============================================================================
# Localization persona + premium branding glossary
# ==============================================================================
LOCALE_PERSONA_MAP = {
    "en": "US Amazon Market",
    "zh-TW": "Taiwan Shopee Market (use Taiwanese Mandarin and emphasize CP値/CP ratio)",
    "ko": "Korean Coupang Market (use natural Korean marketing tone)",
}

# key -> { "match": regex alternation, "hint": short factual guidance }
MADE_IN_JAPAN_GLOSSARY: dict[str, dict[str, str]] = {
    # --- Lacquer & Surface Art ---
    "Urushi": {
        "match": r"(?:urushi|漆|lacquerware)",
        "hint": "Urushi is a 'living' lacquer harvested by hand from rare sap. Unlike plastic, it hardens over decades, becoming more lustrous and durable with age and touch.",
    },
    "Maki-e": {
        "match": r"(?:maki-e|蒔絵|makie)",
        "hint": "The 'sprinkled picture' technique. Artisans use fine bamboo tubes to scatter 24k gold or silver powder onto wet lacquer, creating shimmering, ethereal depth.",
    },
    "Raden": {
        "match": r"(?:raden|螺鈿)",
        "hint": "A luxury inlay technique where ultra-thin slices of iridescent sea shells (abalone) are set into lacquer to capture and refract light like a gemstone.",
    },

    # --- Ceramics & Pottery ---
    "Bizen-yaki": {
        "match": r"(?:bizen|備前焼)",
        "hint": "Fired for 14 days without glaze. The patterns (Yohen) are created solely by the 'alchemy of fire' and ash inside the kiln, making every single piece an unrepeatable miracle.",
    },
    "Kintsugi": {
        "match": r"(?:kintsugi|金継ぎ|kintsukuroi)",
        "hint": "The philosophy of 'Golden Joinery.' It transforms broken ceramics into art using gold-dusted lacquer, celebrating a product's history rather than hiding its scars.",
    },
    "Kutani": {
        "match": r"(?:kutani|九谷焼)",
        "hint": "Characterized by its 'Five Colors' (Gosai) palette. Known for bold, vivid overglaze paintings that have defined Japanese porcelain luxury since the 17th century.",
    },

    # --- Textiles & Weaving ---
    "Nishijin-ori": {
        "match": r"(?:nishijin|西陣織)",
        "hint": "The pinnacle of Japanese weaving from Kyoto. This high-density silk brocade often incorporates real gold threads and was historically reserved for emperors and high-ranking samurai.",
    },
    "Aizome": {
        "match": r"(?:aizome|藍染|indigo)",
        "hint": "Naturally fermented 'Japan Blue.' This organic indigo dye is antibacterial and skin-friendly, evolving its shade over years to reflect the owner's lifestyle.",
    },
    "Shibori": {
        "match": r"(?:shibori|絞り)",
        "hint": "A labor-intensive resist-dyeing method. Every tiny 'bump' or pattern is hand-tied with thread before dyeing, a process that can take a master months to complete for a single garment.",
    },

    # --- Metal & Woodwork ---
    "Nambu Tekki": {
        "match": r"(?:nambu|nanbu|南部鉄器|ironware)",
        "hint": "Traditional ironware from Iwate. These kettles are hand-cast in clay molds and 'charcoal-fired' to create a unique interior layer that purifies water and adds a mellow sweetness to tea.",
    },
    "Magewappa": {
        "match": r"(?:magewappa|曲げわっぱ|bentwood)",
        "hint": "Hand-bent cedar from Akita. This ancient technique uses steam to curve wood into elegant, lightweight forms that possess a natural, antimicrobial cedar aroma.",
    },
    "Sashimono": {
        "match": r"(?:sashimono|指物|joinery)",
        "hint": "Precision 'Blind Joinery.' Pieces are joined using complex interlocking wood-to-wood structures without a single nail or screw, designed to last for generations.",
    },
    "Arita":{
        "match": r"(?:\bArita\b|有田)",
        "hint": "Arita is one of Japan’s most celebrated porcelain regions with centuries of kiln heritage.",
    }
}

# Evidence-Discovery mapping (deterministic, no-LLM copy suggestions)
# Keys are normalized term names (glossary keys stripped).
DISCOVERY_MAP: dict[str, dict[str, str]] = {
    "Kyoto": {
        "category": "Regional Pedigree",
        "title": "Kyoto Heritage Craft",
        "suggested_content": (
            "Kyoto is Japan’s historical capital of craftsmanship—home to workshops that have preserved high-skill techniques for centuries. "
            "A Kyoto origin signals cultural pedigree, artisan discipline, and collectible-grade quality."
        ),
    },
    "Urushi": {
        "category": "Time-as-Luxury",
        "title": "Urushi Lacquer Story",
        "suggested_content": (
            "Urushi is traditional Japanese lacquer—hand-harvested sap, applied in delicate layers, then cured over time. "
            "This slow process creates a deep luster and durability that modern coatings can’t replicate, making the piece feel like a lifelong heirloom."
        ),
    },
    "Maki-e": {
        "category": "Tactile & Sensory",
        "title": "Maki-e Gold Artistry",
        "suggested_content": (
            "Maki-e (蒔絵) is a luxury lacquer art where artisans scatter fine gold or silver powder onto wet lacquer to create shimmering depth. "
            "It’s a technique defined by precision, patience, and a finish that changes subtly with light."
        ),
    },
    "Raden": {
        "category": "Tactile & Sensory",
        "title": "Raden Shell Inlay",
        "suggested_content": (
            "Raden (螺鈿) is a premium inlay technique using ultra-thin slices of iridescent shell embedded into lacquer. "
            "The surface catches light like a gemstone, adding a distinct sense of luxury and rarity."
        ),
    },
    "Bizen-yaki": {
        "category": "Regional Pedigree",
        "title": "Bizen-yaki Kiln-Fired Uniqueness",
        "suggested_content": (
            "Bizen-yaki (備前焼) is celebrated for natural kiln effects—pattern and tone created by fire and ash rather than glaze. "
            "Each piece is unrepeatable, making it closer to art than commodity."
        ),
    },
    "Kintsugi": {
        "category": "Time-as-Luxury",
        "title": "Kintsugi Philosophy",
        "suggested_content": (
            "Kintsugi (金継ぎ) repairs ceramics with lacquer and gold, honoring the object’s history instead of hiding it. "
            "It’s a cultural idea of beauty-through-time—turning wear and story into value."
        ),
    },
    "Kutani": {
        "category": "Regional Pedigree",
        "title": "Kutani ‘Five Colors’ Porcelain",
        "suggested_content": (
            "Kutani (九谷焼) is known for its bold ‘Five Colors’ palette and detailed overglaze painting. "
            "It represents Japanese porcelain luxury with strong visual presence."
        ),
    },
    "Nishijin-ori": {
        "category": "Regional Pedigree",
        "title": "Nishijin-ori Kyoto Weaving",
        "suggested_content": (
            "Nishijin-ori (西陣織) is Kyoto’s pinnacle of brocade weaving—high-density textiles built through complex looms and artisan control. "
            "It signals ceremonial-grade heritage craftsmanship."
        ),
    },
    "Aizome": {
        "category": "Tactile & Sensory",
        "title": "Aizome Japan Blue",
        "suggested_content": (
            "Aizome (藍染) is traditional indigo dyeing. The shade evolves gently with wear, developing character over time. "
            "It’s valued for depth, warmth, and a distinctly Japanese visual identity."
        ),
    },
    "Shibori": {
        "category": "Time-as-Luxury",
        "title": "Shibori Hand-Tied Craft",
        "suggested_content": (
            "Shibori (絞り) patterns are created by hand-binding fabric before dyeing. "
            "The labor intensity behind each motif makes the result feel uniquely human and premium."
        ),
    },
    "Nambu Tekki": {
        "category": "Regional Pedigree",
        "title": "Nambu Tekki Ironware",
        "suggested_content": (
            "Nambu Tekki (南部鉄器) ironware is traditionally cast in regional workshops with meticulous mold-making and finishing. "
            "It’s associated with durability, tradition, and functional beauty."
        ),
    },
    "Magewappa": {
        "category": "Tactile & Sensory",
        "title": "Magewappa Bentwood",
        "suggested_content": (
            "Magewappa (曲げわっぱ) uses steamed wood bent into elegant forms. "
            "The craft highlights natural grain, lightness, and a refined, minimalist Japanese feel."
        ),
    },
    "Sashimono": {
        "category": "Time-as-Luxury",
        "title": "Sashimono Joinery",
        "suggested_content": (
            "Sashimono (指物) emphasizes precise joinery—wood-to-wood structures designed to last for generations. "
            "It represents longevity and engineering-as-art."
        ),
    },
    "Arita": {
        "category": "Regional Pedigree",
        "title": "Arita Porcelain Heritage",
        "suggested_content": (
            "Arita (有田) is one of Japan’s most celebrated porcelain regions with centuries of kiln heritage. "
            "It’s known for its fine, delicate porcelain made from high-quality kaolin clay."
        ),
    },
}

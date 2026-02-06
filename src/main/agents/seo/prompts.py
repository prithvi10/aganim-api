"""
SEO Agent Prompts

Contains all prompts for SEO generation and CTR checking patterns.
"""

# =============================================================================
# SEO Generation Prompts
# =============================================================================

SEO_SYSTEM_PROMPT = """You are a senior SEO strategist specializing in e-commerce product optimization.

Your task is to generate SEO metadata that maximizes click-through rate (CTR) while maintaining accuracy.

CONSTRAINTS:
- Do NOT invent product facts, materials, dimensions, or provenance not present in the content.
- All claims must be grounded in the provided product description.
- Output must be in the TARGET LANGUAGE specified.

SEO TITLE RULES (<= 70 characters):
- Lead with the most important keyword + clear product type
- Keep it readable; truncate filler if near the limit
- Include brand/origin if space permits and present in source

SEO DESCRIPTION RULES (<= 160 characters) - MUST satisfy PST formula:
- (P) Pain/Problem: Start with ONE short problem, question, or desire
- (S) Solution: Follow with a concrete benefit tied to a real product fact
- (T) Trust: Add ONE trust cue ONLY if supported by source (made in Japan, artisan-crafted, etc.)
- End with a simple CTA
- Avoid keyword stuffing

SEO ALT TEXT:
- Describe the main product image accurately
- Include relevant keywords naturally
- Keep under 125 characters

Return ONLY valid JSON with this exact shape:
{
  "seo_title": "...",
  "seo_description": "...",
  "seo_alt_text": "...",
  "seo_insights": {
    "lsi_keywords_used": ["keyword1", "keyword2", ...],
    "search_intent": "Transactional|Informational",
    "competitive_edge": "One unique detail competitors missed"
  }
}
"""

SEO_USER_PROMPT_TEMPLATE = """Generate SEO metadata for this product:

PRODUCT TITLE: {title}
CATEGORY: {category}
TARGET LANGUAGE: {target_locale}

PRODUCT DESCRIPTION:
{description}

COMPETITOR CONTEXT (Top 3 Google results):
{serp_context}

Generate optimized SEO metadata in {target_locale}."""


# =============================================================================
# CTR/PST Check Patterns (Deterministic)
# =============================================================================

# Pain/Problem indicators
PST_PAIN_PATTERNS = [
    r"\?",  # Questions indicate pain/desire
    r"tired of",
    r"struggling",
    r"looking for",
    r"need",
    r"want",
    r"wish",
    r"finally",
    r"discover",
    r"transform",
    r"upgrade",
    r"problem",
    r"solution",
    r"困っている",  # Japanese: troubled
    r"探している",  # Japanese: looking for
    r"欲しい",  # Japanese: want
]

# Solution/Benefit indicators
PST_SOLUTION_PATTERNS = [
    r"benefit",
    r"advantage",
    r"feature",
    r"quality",
    r"premium",
    r"handcraft",
    r"artisan",
    r"traditional",
    r"authentic",
    r"made in",
    r"durable",
    r"\d+\s*(mm|cm|g|kg|oz|inch)",  # Specs
    r"特徴",  # Japanese: feature
    r"品質",  # Japanese: quality
    r"職人",  # Japanese: artisan
]

# Trust indicators
PST_TRUST_PATTERNS = [
    r"free shipping",
    r"送料無料",
    r"made in japan",
    r"日本製",
    r"guarantee",
    r"warranty",
    r"authentic",
    r"certified",
    r"award",
    r"years? of experience",
    r"since \d{4}",
    r"generation",
    r"family",
    r"master",
    r"craftsman",
    r"limited",
    r"exclusive",
]

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
    r"\?",  # Questions indicate pain/desire (half-width)
    r"？",  # Full-width question mark (Japanese)
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
    # Japanese pain/question patterns
    r"困っている",
    r"探している",
    r"欲しい",
    r"ですか",        # question ending
    r"ませんか",      # negative question ("wouldn't you?")
    r"でしょうか",    # polite question
    r"お悩み",        # worry (honorific)
    r"悩み",          # worry
    r"最適",          # ideal/perfect for
    r"ぴったり",      # perfect fit
    r"おすすめ",      # recommended
    r"人気",          # popular
    r"したい",        # want to
    r"してみ",        # try doing
    r"お探し",        # looking for (honorific)
    r"必要",          # necessary
    r"大切",          # important
    r"いかがですか",  # how about?
    r"チェック",      # check (trendy CTA)
    r"見つけ",        # find
    r"選び方",        # how to choose
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
    r"\d+\s*(mm|cm|g|kg|oz|inch)",  # Specs (Western)
    # Japanese solution/benefit patterns
    r"特徴",
    r"品質",
    r"職人",
    r"手作り",
    r"ハンドメイド",
    r"天然",
    r"自然",
    r"本格",
    r"本物",
    r"伝統",
    r"伝統工芸",
    r"こだわり",      # attention to detail
    r"安心",
    r"安全",
    r"高品質",
    r"上質",
    r"厳選",          # carefully selected
    r"実現",          # achieve/deliver
    r"楽しめ",        # can enjoy
    r"味わい",        # flavor/experience
    r"引き立て",      # enhance
    r"\d+[㎝㎜㎖ℊ]",  # Japanese-style unit specs
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
    # English trust — manufacturing/origin
    r"factory",
    r"established",
    r"founded",
    r"brewer",
    r"brewery",
    r"distiller",
    r"winery",
    r"crafted",
    r"handcraft",
    r"produced",
    r"manufactured",
    r"artisan",
    r"handmade",
    r"hand[- ]?made",
    r"product of",
    r"made in \w+",
    r"imported from",
    r"sourced from",
    r"origin",
    r"prefecture",
    r"region",
    r"estate",
    r"tradition",
    r"heritage",
    r"premium",
    r"small[- ]?batch",
    r"100%",
    r"organic",
    r"natural",
    r"no additives",
    r"preservative[- ]?free",
    r"no preservatives",
    # Japanese trust patterns — craft regions
    r"京都",
    r"有田",
    r"九谷",
    r"備前",
    r"南部",
    r"信楽",
    r"益子",
    r"瀬戸",
    r"清水焼",
    r"藤沢",
    r"神奈川",
    # Japanese trust patterns — craftsmanship
    r"職人",
    r"匠",
    r"手作り",
    r"手仕事",
    r"伝統工芸",
    r"伝統的",
    r"醸造",
    r"製造",
    # Japanese trust patterns — heritage
    r"老舗",
    r"創業",
    r"\d+年",         # N years (heritage indicator)
    # Japanese trust patterns — quality assurance
    r"安心",
    r"信頼",
    r"保証",
    r"品質保証",
    r"無添加",
    r"無着色",
    # Japanese trust patterns — exclusivity
    r"限定",
    r"数量限定",
    # Japanese trust patterns — origin
    r"国産",
    r"メイドインジャパン",
    r"産地",
    r"生産地",
    # Japanese trust patterns — awards
    r"受賞",
    r"認定",
]

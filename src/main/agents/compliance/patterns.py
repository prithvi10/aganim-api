"""
Compliance Agent Regex Patterns

Patterns for quick pre-filtering of content before LLM analysis.
These catch obvious violations without needing an LLM call.
"""

# FDA-related patterns
# These match health/medical claims that may violate FDA regulations
FDA_PATTERNS = [
    r"\bcures?\b",                          # "cure", "cures"
    r"\btreat(s|ing|ment)?\b",              # "treat", "treats", "treating", "treatment"
    r"\bprevent(s|ing)?\s+disease",         # "prevents disease", "preventing disease"
    r"\bFDA\s+approved\b",                  # "FDA approved" (often misused)
    r"\bmedically\s+proven\b",              # "medically proven"
    r"\bclinically\s+proven\b",             # "clinically proven"
    r"\bguaranteed\s+results?\b",           # "guaranteed results"
    r"\b100%\s+effective\b",                # "100% effective"
    r"\bmiracl(e|ous)\b",                   # "miracle", "miraculous"
    r"\bheals?\b",                          # "heal", "heals"
    r"\banti[- ]?aging\b",                  # "anti-aging", "antiaging"
    r"\bdetox(ify|ifies|ification)?\b",     # "detox", "detoxify", etc.
]

# FTC-related patterns
# These match advertising claims that may violate FTC regulations
FTC_PATTERNS = [
    r"\b(best|#1|number\s+one)\s+in\s+(the\s+)?(world|market)\b",  # "best in the world"
    r"\brisk[- ]free\b",                    # "risk-free", "risk free"
    r"\bno\s+side\s+effects?\b",            # "no side effects"
    r"\bguaranteed\s+(weight\s+loss|results?)\b",  # "guaranteed weight loss"
    r"\bscientifically\s+proven\b",         # "scientifically proven" (often unverified)
    r"\bunbeatable\b",                      # "unbeatable"
    r"\bimpossible\s+to\s+find\s+cheaper\b",  # Price comparison claims
    r"\bfree\s+trial\b",                    # Free trial (often has conditions)
    r"\blimited\s+time\s+offer\b",          # Urgency claims (need verification)
]

# Health supplement patterns
# Additional patterns for dietary supplements and health products
SUPPLEMENT_PATTERNS = [
    r"\bboosts?\s+immun(e|ity)\b",          # "boosts immunity"
    r"\bincreases?\s+energy\b",             # "increases energy"
    r"\bnatural\s+cure\b",                  # "natural cure"
    r"\bherbal\s+remedy\b",                 # "herbal remedy"
    r"\bweight\s+loss\s+(pill|supplement)\b",  # "weight loss pill"
]

# Combine all patterns for convenience
ALL_PATTERNS = FDA_PATTERNS + FTC_PATTERNS + SUPPLEMENT_PATTERNS


def get_pattern_category(pattern: str) -> str:
    """Get the category for a matched pattern."""
    if pattern in FDA_PATTERNS:
        return "FDA"
    elif pattern in FTC_PATTERNS:
        return "FTC"
    elif pattern in SUPPLEMENT_PATTERNS:
        return "Supplement"
    return "Unknown"

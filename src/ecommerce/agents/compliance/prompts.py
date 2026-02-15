"""
Compliance Agent Prompts

FDA, FTC, and general compliance checking prompts.
"""

# System prompt for compliance judge
SYSTEM_PROMPT = """You are a compliance expert specializing in e-commerce content review.

Your role is to identify potential regulatory violations in product descriptions, including:
- FDA violations (health claims, disease treatment claims)
- FTC violations (false advertising, unsubstantiated claims)
- Misleading statements or exaggerations

Be thorough but fair. Focus on actual violations, not stylistic choices.
Consider context - some claims may be legitimate if properly qualified.

Rate severity as:
- "low": Minor issues or borderline cases
- "medium": Clear violations that should be addressed
- "high": Serious violations that could result in legal action
"""

# Main compliance check prompt template
CHECK_PROMPT_TEMPLATE = """Review the following product content for compliance issues:

---
{content}
---
{flags_section}

Analyze for:
1. FDA violations (health claims, medical claims)
2. FTC violations (false advertising, unsubstantiated claims)
3. Misleading or exaggerated statements
4. Claims that require disclaimers

Provide a comprehensive compliance assessment.
"""

# Template for regex flags section
REGEX_FLAGS_SECTION_TEMPLATE = """
The following potential issues were flagged by automated scanning:
{flags}

Please verify these flags and identify any additional issues.
"""

# Empty flags section (when no regex matches found)
EMPTY_FLAGS_SECTION = ""

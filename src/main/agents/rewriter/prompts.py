"""
Rewriter Agent Prompts

All prompts specific to the RewriterAgent are centralized here
for easy iteration and maintenance.
"""

# Re-export from config/prompts.py for backward compatibility
# These are the "legacy" prompts that are shared/general purpose
from src.main.config.prompts import (
    SYSTEM_PROMPT as BASE_SYSTEM_PROMPT,
    TONE_PROMPTS,
    VALUE_DISCOVERY_PROMPT,
    BRAND_CONTEXT_INJECTION_TEMPLATE,
)

# Export for use by agent
REWRITER_SYSTEM_PROMPT = BASE_SYSTEM_PROMPT

# User prompt template for product copy generation
USER_PROMPT_TEMPLATE = """
Product Name: {title}
Category: {category}
Target Locale: {target_locale}

The following Japanese text is pre-labeled with [Section] tags. Translate and beautify EACH section individually, preserving order and structure. Use the Architectural Rules from the system prompt.

Pre-labeled Japanese Text:
{description}
""".strip()

# Learned preferences injection template
LEARNED_PREFERENCES_TEMPLATE = """
### LEARNED USER PREFERENCES:
Apply these corrections from past feedback:
{rules}
""".strip()

# Locale persona injection template
LOCALE_PERSONA_TEMPLATE = """
### TARGET LOCALE PERSONA:
{persona}
""".strip()

# Compliance feedback template (for adversarial regeneration)
COMPLIANCE_FEEDBACK_TEMPLATE = """
### COMPLIANCE FEEDBACK:
The previous version had compliance issues. Please regenerate while avoiding these:
{feedback}
""".strip()

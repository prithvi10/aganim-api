"""
Rewriter Agent Prompts

All prompts specific to the RewriterAgent are centralized here
for easy iteration and maintenance.
"""

# Re-export from config/prompts.py for backward compatibility
# These are the "legacy" prompts that are shared/general purpose
from src.shared.config.prompts import (
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


# Refinement mode prompt (for user feedback-based regeneration)
REWRITER_REFINE_PROMPT = """You are a Senior Editor reviewing a draft product description.

### CONTEXT:
You have a draft that is approximately 90% correct. Your job is to modify it based STRICTLY on the User Feedback below.

### RULES:
1. Do NOT rewrite the whole thing from scratch unless explicitly asked.
2. Preserve the existing structure, tone, and style.
3. Make only the changes requested in the feedback.
4. Maintain the same JSON output format with keys: title, description, discovered_values.
5. Keep all HTML formatting and section structure intact unless specifically asked to change it.
6. All output MUST remain in the language of the Target Locale: {target_locale}

### CURRENT DRAFT (Title):
{current_title}

### CURRENT DRAFT (Description):
{current_description}

### USER FEEDBACK:
{user_feedback}

### SOURCE DATA (for reference only - do not re-translate from scratch):
Product Name: {source_title}
Category: {category}
Original Description:
{source_description}

### OUTPUT:
Return the refined version in the same JSON structure. Only modify what the user feedback requests:
{{
  "title": "...",
  "description": "...",
  "discovered_values": [...]
}}
""".strip()


# Refinement user prompt — include the actual feedback so the LLM prioritises it
REFINE_USER_PROMPT = """Apply the following user feedback to refine the draft.
Make ONLY the changes the feedback requests. Preserve everything else. Return valid JSON only.

### USER FEEDBACK:
{user_feedback}""".strip()

"""
Product Content Templates - Prompts for RewriterAgent.

Templates for product-centric content generation.
"""

from .registry import (
    ContentTemplate,
    TemplateInput,
    TemplateCategory,
    AgentType,
    register_template,
)

# Product Title Generator
PRODUCT_TITLE_SYSTEM_PROMPT = """You are a product title optimization expert.

Generate compelling, SEO-friendly product titles that:
- Include key product attributes
- Use power words that drive clicks
- Stay under 70 characters
- Match the brand voice
- Are optimized for search engines

Return ONLY valid JSON with this structure:
{
  "title": "Optimized product title",
  "alternatives": ["Alternative 1", "Alternative 2", "Alternative 3"]
}
"""

PRODUCT_TITLE_USER_PROMPT = """Product: {title}
Category: {category}
Target Locale: {target_locale}
Description: {description}

Generate an optimized product title and 3 alternatives.
"""

# Collection Description
COLLECTION_DESCRIPTION_SYSTEM_PROMPT = """You are an e-commerce copywriter.

Generate collection/category page descriptions that:
- Introduce the collection theme
- Highlight key products/features
- Include relevant keywords
- Encourage browsing
- Match the brand voice

Return ONLY valid JSON:
{
  "description": "Collection description HTML",
  "meta_description": "SEO meta description (160 chars max)"
}
"""

COLLECTION_DESCRIPTION_USER_PROMPT = """Collection Name: {collection_name}
Category: {category}
Products in Collection: {products}
Target Locale: {target_locale}

Generate a compelling collection description.
"""

# Product FAQ Generator
PRODUCT_FAQ_SYSTEM_PROMPT = """You are a customer service expert.

Generate FAQs based on product details that:
- Answer common customer questions
- Address size/fit/material concerns
- Cover shipping and care instructions
- Reduce support tickets
- Use clear, helpful language

Return ONLY valid JSON:
{
  "faqs": [
    {
      "question": "Question text",
      "answer": "Answer text"
    }
  ]
}
"""

PRODUCT_FAQ_USER_PROMPT = """Product: {title}
Category: {category}
Description: {description}
Target Locale: {target_locale}

Generate 5-8 FAQs that customers would ask about this product.
"""

# Landing Page Hero
LANDING_HERO_SYSTEM_PROMPT = """You are a conversion copywriter.

Generate landing page hero section copy that:
- Has a compelling headline (under 60 characters)
- Includes a strong value proposition
- Has a clear call-to-action
- Creates urgency or interest
- Matches the brand voice

Return ONLY valid JSON:
{
  "headline": "Main headline",
  "subheadline": "Supporting subheadline",
  "cta_text": "Call-to-action button text",
  "hero_description": "Short hero section description (2-3 sentences)"
}
"""

LANDING_HERO_USER_PROMPT = """Product: {title}
Category: {category}
Description: {description}
Target Locale: {target_locale}

Generate landing page hero section copy.
"""


def register_product_templates():
    """Register all product templates."""
    
    # Product Description (existing - reference only)
    register_template(ContentTemplate(
        id="product/description",
        name="Product Description",
        category=TemplateCategory.PRODUCT,
        agent_type=AgentType.REWRITER,
        description="Generate localized product descriptions from Japanese source text",
        inputs=[
            TemplateInput(name="title", label="Product Title", required=True),
            TemplateInput(name="description", label="Product Description", required=True, input_type="textarea"),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="html",
        system_prompt="",  # Uses existing REWRITER_SYSTEM_PROMPT
        user_prompt_template="",  # Uses existing USER_PROMPT_TEMPLATE
        tier_required="Free",
    ))
    
    # Product Title
    register_template(ContentTemplate(
        id="product/title",
        name="Product Title Generator",
        category=TemplateCategory.PRODUCT,
        agent_type=AgentType.REWRITER,
        description="Generate SEO-optimized product titles",
        inputs=[
            TemplateInput(name="title", label="Current Title", required=True),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="description", label="Product Description", required=True, input_type="textarea"),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=PRODUCT_TITLE_SYSTEM_PROMPT,
        user_prompt_template=PRODUCT_TITLE_USER_PROMPT,
        tier_required="Free",
    ))
    
    # Collection Description
    register_template(ContentTemplate(
        id="product/collection",
        name="Collection Description",
        category=TemplateCategory.PRODUCT,
        agent_type=AgentType.REWRITER,
        description="Generate collection/category page descriptions",
        inputs=[
            TemplateInput(name="collection_name", label="Collection Name", required=True),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="products", label="Products in Collection", required=False, input_type="textarea"),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="html",
        system_prompt=COLLECTION_DESCRIPTION_SYSTEM_PROMPT,
        user_prompt_template=COLLECTION_DESCRIPTION_USER_PROMPT,
        tier_required="Basic",
    ))
    
    # Product FAQ
    register_template(ContentTemplate(
        id="product/faq",
        name="Product FAQ Generator",
        category=TemplateCategory.PRODUCT,
        agent_type=AgentType.REWRITER,
        description="Generate FAQs from product details",
        inputs=[
            TemplateInput(name="title", label="Product Title", required=True),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="description", label="Product Description", required=True, input_type="textarea"),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=PRODUCT_FAQ_SYSTEM_PROMPT,
        user_prompt_template=PRODUCT_FAQ_USER_PROMPT,
        tier_required="Basic",
    ))
    
    # Landing Page Hero
    register_template(ContentTemplate(
        id="product/landing-hero",
        name="Landing Page Hero",
        category=TemplateCategory.PRODUCT,
        agent_type=AgentType.REWRITER,
        description="Generate hero section copy for product landing pages",
        inputs=[
            TemplateInput(name="title", label="Product Title", required=True),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="description", label="Product Description", required=True, input_type="textarea"),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=LANDING_HERO_SYSTEM_PROMPT,
        user_prompt_template=LANDING_HERO_USER_PROMPT,
        tier_required="Standard",
    ))

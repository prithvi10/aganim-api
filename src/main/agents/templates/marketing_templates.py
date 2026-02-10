"""
Marketing Content Templates - Prompts for MarketingAgent.

Templates for promotional and campaign content generation.
"""

from .registry import (
    ContentTemplate,
    TemplateInput,
    TemplateCategory,
    AgentType,
    register_template,
)

# Email - Product Launch
EMAIL_LAUNCH_SYSTEM_PROMPT = """You are an email marketing expert.

Generate product launch emails that:
- Create excitement and urgency
- Highlight key product benefits
- Include a clear CTA
- Match the brand voice
- Work for both subject line and body

Return ONLY valid JSON:
{
  "subject": "Email subject line (50 chars max)",
  "preheader": "Preheader text (100 chars max)",
  "body": "Email body HTML",
  "cta_text": "Call-to-action button text"
}
"""

EMAIL_LAUNCH_USER_PROMPT = """Product: {title}
Category: {category}
Description: {description}
Launch Date: {launch_date}
Target Locale: {target_locale}

Generate a product launch email.
"""

# Email - Abandoned Cart
EMAIL_ABANDONED_SYSTEM_PROMPT = """You are a conversion optimization expert.

Generate abandoned cart recovery emails that:
- Remind without being pushy
- Address common objections
- Create gentle urgency
- Offer help or incentives
- Have a clear CTA

Return ONLY valid JSON:
{
  "subject": "Email subject line (50 chars max)",
  "preheader": "Preheader text (100 chars max)",
  "body": "Email body HTML",
  "cta_text": "Call-to-action button text"
}
"""

EMAIL_ABANDONED_USER_PROMPT = """Product: {title}
Category: {category}
Price: {price}
Target Locale: {target_locale}

Generate an abandoned cart recovery email.
"""

# Email - Welcome
EMAIL_WELCOME_SYSTEM_PROMPT = """You are an email marketing expert.

Generate welcome emails for new subscribers that:
- Welcome warmly
- Set expectations
- Highlight brand values
- Include a CTA to explore products
- Match the brand voice

Return ONLY valid JSON:
{
  "subject": "Email subject line (50 chars max)",
  "preheader": "Preheader text (100 chars max)",
  "body": "Email body HTML",
  "cta_text": "Call-to-action button text"
}
"""

EMAIL_WELCOME_USER_PROMPT = """Brand Name: {brand_name}
Target Locale: {target_locale}

Generate a welcome email for new subscribers.
"""

# Ad Copy - Social (Facebook/Instagram)
AD_COPY_SOCIAL_SYSTEM_PROMPT = """You are a performance marketing expert.

Generate social media ad copy that:
- Stops the scroll with a strong hook
- Communicates value in 125 characters (primary text)
- Includes a compelling headline (40 chars)
- Has a clear CTA
- Creates urgency or interest

Return ONLY valid JSON:
{
  "primary_text": "Main ad copy (125 chars max)",
  "headline": "Ad headline (40 chars max)",
  "description": "Ad description (optional)",
  "cta": "Call-to-action button text"
}
"""

AD_COPY_SOCIAL_USER_PROMPT = """Product: {title}
Category: {category}
Description: {description}
Target Locale: {target_locale}
Platform: {platform}

Generate social media ad copy.
"""

# Ad Copy - Search (Google Ads)
AD_COPY_SEARCH_SYSTEM_PROMPT = """You are a Google Ads specialist.

Generate search ad copy that:
- 3 headlines (30 chars each)
- 2 descriptions (90 chars each)
- Includes relevant keywords
- Has a strong CTA
- Matches search intent

Return ONLY valid JSON:
{
  "headlines": ["Headline 1 (30 chars)", "Headline 2 (30 chars)", "Headline 3 (30 chars)"],
  "descriptions": ["Description 1 (90 chars)", "Description 2 (90 chars)"],
  "path1": "Display path 1",
  "path2": "Display path 2"
}
"""

AD_COPY_SEARCH_USER_PROMPT = """Product: {title}
Category: {category}
Keywords: {keywords}
Target Locale: {target_locale}

Generate Google Ads search ad copy.
"""


def register_marketing_templates():
    """Register all marketing templates."""
    
    # Email - Launch
    register_template(ContentTemplate(
        id="marketing/email-launch",
        name="Launch Email",
        category=TemplateCategory.MARKETING,
        agent_type=AgentType.MARKETING,
        description="Generate product launch announcement emails",
        inputs=[
            TemplateInput(name="title", label="Product Title", required=True),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="description", label="Product Description", required=True, input_type="textarea"),
            TemplateInput(name="launch_date", label="Launch Date", required=False),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=EMAIL_LAUNCH_SYSTEM_PROMPT,
        user_prompt_template=EMAIL_LAUNCH_USER_PROMPT,
    ))
    
    # Email - Abandoned Cart
    register_template(ContentTemplate(
        id="marketing/email-abandoned",
        name="Abandoned Cart Email",
        category=TemplateCategory.MARKETING,
        agent_type=AgentType.MARKETING,
        description="Generate abandoned cart recovery emails",
        inputs=[
            TemplateInput(name="title", label="Product Title", required=True),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="price", label="Price", required=False),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=EMAIL_ABANDONED_SYSTEM_PROMPT,
        user_prompt_template=EMAIL_ABANDONED_USER_PROMPT,
    ))
    
    # Email - Welcome
    register_template(ContentTemplate(
        id="marketing/email-welcome",
        name="Welcome Email",
        category=TemplateCategory.MARKETING,
        agent_type=AgentType.MARKETING,
        description="Generate welcome emails for new subscribers",
        inputs=[
            TemplateInput(name="brand_name", label="Brand Name", required=True),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=EMAIL_WELCOME_SYSTEM_PROMPT,
        user_prompt_template=EMAIL_WELCOME_USER_PROMPT,
    ))
    
    # Ad Copy - Social
    register_template(ContentTemplate(
        id="marketing/ad-facebook",
        name="Facebook/Instagram Ad",
        category=TemplateCategory.MARKETING,
        agent_type=AgentType.MARKETING,
        description="Generate social media ad copy",
        inputs=[
            TemplateInput(name="title", label="Product Title", required=True),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="description", label="Product Description", required=True, input_type="textarea"),
            TemplateInput(name="platform", label="Platform", required=False),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=AD_COPY_SOCIAL_SYSTEM_PROMPT,
        user_prompt_template=AD_COPY_SOCIAL_USER_PROMPT,
    ))
    
    # Ad Copy - Search
    register_template(ContentTemplate(
        id="marketing/ad-google",
        name="Google Ads",
        category=TemplateCategory.MARKETING,
        agent_type=AgentType.MARKETING,
        description="Generate Google Ads search ad copy",
        inputs=[
            TemplateInput(name="title", label="Product Title", required=True),
            TemplateInput(name="category", label="Category", required=True),
            TemplateInput(name="keywords", label="Keywords", required=False),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=AD_COPY_SEARCH_SYSTEM_PROMPT,
        user_prompt_template=AD_COPY_SEARCH_USER_PROMPT,
    ))



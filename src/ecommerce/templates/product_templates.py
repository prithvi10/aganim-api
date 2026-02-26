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

# Artisan / Behind-the-Scenes Blog Post
PRODUCT_BLOG_POST_SYSTEM_PROMPT = """You are a brand storytelling expert who writes compelling blog posts for artisan and craft brands.

Write a long-form blog post (800-1200 words) about the given subject. The post should:
- Educate readers about the craft, technique, or process
- Weave the brand story and heritage into the narrative naturally
- Include sensory details that make the reader feel the craftsmanship
- Position the brand as an authority in its field
- Be formatted in clean HTML with <h2> sub-headings, <p> paragraphs, and occasional <blockquote> for emphasis
- End with a soft call-to-action that links the subject back to the brand's products

Subjects can include but are not limited to:
  manufacturing processes, material sourcing, artisan techniques,
  shipping & packaging philosophy, sustainability practices,
  the history of a craft, behind-the-scenes workshop tours,
  seasonal collections, collaborations, or cultural traditions.

[Content Priority]
Focus primarily on the Category and Additional Context provided by the user.
These are the core of the article. Brand heritage context (if provided) should
subtly inform tone and philosophy -- it must NOT dominate the narrative or
overshadow the user's requested subject.

[Visual Art Direction Requirements]
After writing the blog, analyze the content and generate a 'Visual Brief' for
a high-end editorial Hero Image that accompanies the article.
- Focus purely on the physical subject, textures, and environment described in the article.
- STRICT RULE: No actors, no faces, no human beings. Focus on "still life" or "process" shots.
- hero_subject must describe a concrete photographic scene, e.g. "Close-up of steam rising from a freshly poured cup of dark coffee".
- surface must be a physical surface, e.g. "A rustic, weathered oak tabletop".
- environment must be a blurred background atmosphere, e.g. "A softly blurred, sunlit minimalist kitchen corner".
- lighting must define the light source and shadow quality, e.g. "Soft side-lighting with gentle, long shadows".

Return ONLY valid JSON:
{
  "title": "Blog post title",
  "meta_description": "SEO meta description (under 160 characters)",
  "body_html": "<h2>...</h2><p>...</p>...",
  "tags": ["tag1", "tag2", "tag3"],
  "visual_brief": {
    "hero_subject": "Concrete photographic subject from the article",
    "surface": "Physical surface description",
    "environment": "Blurred background atmosphere",
    "lighting": "Light source and shadow quality"
  }
}
"""

PRODUCT_BLOG_POST_USER_PROMPT = """Subject / Topic: {topic}
Category: {category}
Additional Context: {context}
Target Locale: {target_locale}

Write an engaging blog post about this subject, connecting it to the brand's story and products.
"""


def register_product_templates():
    """Register all product templates."""

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
    ))

    # Artisan / Behind-the-Scenes Blog Post
    register_template(ContentTemplate(
        id="product/blog-post",
        name="Brand Blog Post",
        category=TemplateCategory.PRODUCT,
        agent_type=AgentType.REWRITER,
        description="Blog about manufacturing, artisan craft, shipping & more",
        inputs=[
            TemplateInput(name="topic", label="Subject / Topic", required=True,
                          description="e.g. 'Our wood-kiln firing process', 'How we source Shigaraki clay', 'The art of gift wrapping'"),
            TemplateInput(name="category", label="Category", required=True,
                          description="e.g. Manufacturing, Shipping, Artisan Techniques, Sustainability"),
            TemplateInput(name="context", label="Additional Context", required=False, input_type="textarea",
                          description="Any extra details, product mentions, or angles to include"),
            TemplateInput(name="target_locale", label="Target Locale", required=True),
        ],
        output_format="json",
        system_prompt=PRODUCT_BLOG_POST_SYSTEM_PROMPT,
        user_prompt_template=PRODUCT_BLOG_POST_USER_PROMPT,
    ))

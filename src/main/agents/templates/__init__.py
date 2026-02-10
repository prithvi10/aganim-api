"""
Template system for content generation.

Provides a registry of content templates that can be used by RewriterAgent
and MarketingAgent to generate different types of content.
"""

from .registry import ContentTemplate, TEMPLATE_REGISTRY, get_template, list_templates, TemplateCategory, AgentType

# Import template modules
from .product_templates import register_product_templates
from .marketing_templates import register_marketing_templates

# Register all templates on package import
register_product_templates()
register_marketing_templates()

__all__ = [
    "ContentTemplate",
    "TEMPLATE_REGISTRY",
    "get_template",
    "list_templates",
    "TemplateCategory",
    "AgentType",
]

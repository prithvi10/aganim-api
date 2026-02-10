"""
Template Registry - Central registry for all content templates.

Templates are organized by category (product/marketing) and agent type.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class TemplateCategory(str, Enum):
    """Template categories."""
    PRODUCT = "product"
    MARKETING = "marketing"


class AgentType(str, Enum):
    """Agent types that handle templates."""
    REWRITER = "rewriter"
    MARKETING = "marketing"


@dataclass
class TemplateInput:
    """Input field definition for a template."""
    name: str
    label: str
    required: bool = True
    input_type: str = "text"  # text, textarea, select, etc.
    description: str = ""


@dataclass
class ContentTemplate:
    """
    Content template definition.
    
    Each template defines:
    - Inputs required from user
    - System and user prompts
    - Output format
    - Tier requirements
    """
    id: str  # e.g., "product/description", "marketing/email-launch"
    name: str  # "Product Description"
    category: TemplateCategory
    agent_type: AgentType
    description: str
    inputs: List[TemplateInput] = field(default_factory=list)
    output_format: str = "html"  # html, markdown, plain
    system_prompt: str = ""
    user_prompt_template: str = ""
    tier_required: str = "Free"  # Free, Basic, Standard, Pro


# Template registry - populated by importing template modules
TEMPLATE_REGISTRY: Dict[str, ContentTemplate] = {}


def register_template(template: ContentTemplate) -> None:
    """Register a template in the global registry. Overwrites if already registered."""
    TEMPLATE_REGISTRY[template.id] = template


def get_template(template_id: str) -> Optional[ContentTemplate]:
    """Get a template by ID."""
    return TEMPLATE_REGISTRY.get(template_id)


def list_templates(
    category: Optional[TemplateCategory] = None,
    agent_type: Optional[AgentType] = None,
    tier: Optional[str] = None,
) -> List[ContentTemplate]:
    """
    List templates with optional filtering.
    
    Args:
        category: Filter by category (product/marketing)
        agent_type: Filter by agent type (rewriter/marketing)
        tier: Filter by minimum tier required
    
    Returns:
        List of matching templates
    """
    templates = list(TEMPLATE_REGISTRY.values())
    
    if category:
        templates = [t for t in templates if t.category == category]
    
    if agent_type:
        templates = [t for t in templates if t.agent_type == agent_type]
    
    if tier:
        tier_order = ["Free", "Basic", "Standard", "Pro"]
        tier_index = tier_order.index(tier) if tier in tier_order else -1
        if tier_index >= 0:
            templates = [
                t for t in templates
                if tier_order.index(t.tier_required) <= tier_index
            ]
    
    return sorted(templates, key=lambda t: t.id)

from __future__ import annotations
from pydantic import BaseModel
from src.ecommerce.config.configs import DEFAULT_PRODUCT_CATEGORY
from typing import Any, Literal

class RewriteRequest(BaseModel):
    product_name: str
    japanese_description: str
    category: str = DEFAULT_PRODUCT_CATEGORY # e.g., "Kitchenware", "Apparel"
    stream: bool = False # New flag for streaming requests
    product_id: int | None = None # Optional: ID of the product to update in Shopify
    target_locale: str | None = None # Optional: The target locale for the translation (e.g. "en", "zh-TW")
    # When true and the target locale is English, keep metric values and append US customary equivalents in parentheses.
    auto_convert_units: bool = False
    # Requested tone profile (Standard/Pro only; Basic is forced to professional).
    tone_profile: Literal["professional", "luxury", "minimalist", "playful"] | None = None
    # When true, strip non-product/misc metadata from the description entirely (default ON).
    remove_irrelevant_content: bool = True
    # When true, inject brand-soul context via RAG (Standard+ only).
    brand_soul_enabled: bool = False

class BulkRewriteRequest(BaseModel):
    product_name: str
    japanese_description: str
    category: str = DEFAULT_PRODUCT_CATEGORY
    product_id: int | None = None
    target_locales: list[str]
    # When true, apply unit conversion behavior for English locales in this bulk request.
    auto_convert_units: bool = False
    # Requested tone profile (Standard/Pro only; Basic is forced to professional).
    tone_profile: Literal["professional", "luxury", "minimalist", "playful"] | None = None
    # When true, strip non-product/misc metadata from the description entirely (default ON).
    remove_irrelevant_content: bool = True
    # When true, inject brand-soul context via RAG (Standard+ only).
    brand_soul_enabled: bool = False

class OnboardingRequest(BaseModel):
    username: str # This will be the shop domain
    email: str | None = None
    plan_id: int

class OnboardingResponse(BaseModel):
    user_id: int
    username: str
    plan_name: str
    api_key: str # The raw API key (shown only once)


# ==============================================================================
# Admin Extension Agent (Action-based) API
# ==============================================================================
class AgentRequest(BaseModel):
    """
    Agnostic, action-based payload for Admin UI extensions and other clients.
    """
    action: str
    context: dict[str, Any] = {}
    product_data: dict[str, Any] = {}


class AgentResponse(BaseModel):
    status: Literal["success"]
    data: dict[str, Any]


class BrandContextIngestRequest(BaseModel):
    urls: list[str] = []
    brand_persona: str | None = None
    core_pillars: list[str] = []
    raw_text: str | None = None
    file_text: str | None = None


class BrandContextFileExtractRequest(BaseModel):
    file_b64: str
    mime_type: str


class BrandContextUpdateRequest(BaseModel):
    clean_text_en: str
    clean_text_ja: str | None = None


# ==============================================================================
# Agentic Architecture API Models
# ==============================================================================

class MissionRequest(BaseModel):
    """
    Request to create a new agent mission for product optimization.
    
    For ad-hoc agent execution, specify requested_agents with the agent names
    to run only those agents instead of the full tier-based workflow.
    """
    product_id: str
    product_name: str
    japanese_description: str
    category: str = "General"
    target_locale: str = "en"
    tone_profile: Literal["professional", "luxury", "minimalist", "playful"] = "professional"
    brand_soul_enabled: bool = False
    # Ad-hoc agent selection: specify agent names to run only those agents
    # e.g., ["CopywriterAgent"], ["MarketingAgent"], ["PriceScoutAgent", "ComplianceAgent"]
    requested_agents: list[str] | None = None
    # Mission Architect: custom pipeline config with per-step human gates
    # e.g., [{"agent_name": "PriceScoutAgent", "has_gate": true}, {"agent_name": "RewriterAgent", "has_gate": false}]
    # When provided, overrides both requested_agents and tier-based workflow.
    workflow_config: list[dict[str, Any]] | None = None
    # Product featured image URL — used by VisualAgent for image generation
    image_url: str | None = None
    # Theme for ImageRefinementAgent background styling
    refinement_theme: str = "clean"
    # Extra context from the Mission Wizard (blog topic, collection info, etc.)
    # Merged into raw_input so agents can access it via state.raw_input.
    extra_context: dict[str, Any] | None = None


class BulkMissionPreferences(BaseModel):
    tone_profile: Literal["professional", "luxury", "minimalist", "playful"] = "professional"
    brand_soul_enabled: bool = False
    us_units_conversion: bool = True
    target_market: str = "en"


class BulkMissionRequest(BaseModel):
    mission_type: Literal["text_only", "full_launch"]
    preferences: BulkMissionPreferences


class CorrectionRequest(BaseModel):
    """
    Request to submit a user correction for agent learning.
    """
    agent_role: str  # "Copywriter", "PriceScout", "Compliance"
    original_output: str
    user_correction: str
    product_id: str | None = None
    context_metadata: dict[str, Any] = {}


# ==============================================================================
# Step-by-Step Journey API Models
# ==============================================================================

class RegenerateRequest(BaseModel):
    """
    Request to regenerate the current agent's output with optional feedback.
    """
    feedback: str | None = None


class StepResponse(BaseModel):
    """
    Response for step-by-step journey endpoints.
    """
    mission_id: str
    current_agent: str
    current_agent_index: int
    total_agents: int
    status: str
    agent_output: dict[str, Any] | None = None
    can_continue: bool
    can_skip: bool
    is_final: bool
    workflow_agents: list[str] = []
    skipped_agents: list[str] = []


class MissionStatusResponse(BaseModel):
    """
    Response for getting mission status.
    """
    mission_id: str
    shop_id: str
    product_id: str
    status: str
    plan_tier: str
    current_agent_index: int
    total_agents: int
    current_agent: str | None = None
    workflow_agents: list[str] = []
    skipped_agents: list[str] = []
    agent_outputs: dict[str, Any] = {}
    logs: list[str] = []
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    current_state: dict[str, Any] | None = None

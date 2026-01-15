from pydantic import BaseModel
from src.main.config.configs import DEFAULT_PRODUCT_CATEGORY
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

class BulkRewriteRequest(BaseModel):
    product_name: str
    japanese_description: str
    category: str = DEFAULT_PRODUCT_CATEGORY
    product_id: int | None = None
    target_locales: list[str]
    # When true, apply unit conversion behavior for English locales in this bulk request.
    auto_convert_units: bool = False

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

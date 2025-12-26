from pydantic import BaseModel
from src.main.config.configs import DEFAULT_PRODUCT_CATEGORY

class RewriteRequest(BaseModel):
    product_name: str
    japanese_description: str
    category: str = DEFAULT_PRODUCT_CATEGORY # e.g., "Kitchenware", "Apparel"
    stream: bool = False # New flag for streaming requests
    product_id: int | None = None # Optional: ID of the product to update in Shopify
    target_locale: str | None = None # Optional: The target locale for the translation (e.g. "en", "zh-TW")

class OnboardingRequest(BaseModel):
    username: str # This will be the shop domain
    email: str | None = None
    plan_id: int

class OnboardingResponse(BaseModel):
    user_id: int
    username: str
    plan_name: str
    api_key: str # The raw API key (shown only once)

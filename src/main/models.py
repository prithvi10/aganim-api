from pydantic import BaseModel
from .configs import DEFAULT_PRODUCT_CATEGORY

class RewriteRequest(BaseModel):
    product_name: str
    japanese_description: str
    category: str = DEFAULT_PRODUCT_CATEGORY # e.g., "Kitchenware", "Apparel"

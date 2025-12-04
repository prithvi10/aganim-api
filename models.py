from pydantic import BaseModel

class RewriteRequest(BaseModel):
    product_name: str
    japanese_description: str
    category: str = "General Goods" # e.g., "Kitchenware", "Apparel"


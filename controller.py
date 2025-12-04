from fastapi import APIRouter, HTTPException, Depends
from models import RewriteRequest
from services import OpenAIService
from security import verify_shopify_session

router = APIRouter()
openai_service = OpenAIService()

@router.post("/api/generate-copy")
async def generate_copy(
    request: RewriteRequest,
    shop: str = Depends(verify_shopify_session)
):
    print(f"✅ Verified request from: {shop}")
    try:
        english_copy = openai_service.generate_copy(
            product_name=request.product_name,
            category=request.category,
            japanese_description=request.japanese_description
        )

        return {
            "status": "success",
            "english_copy": english_copy
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


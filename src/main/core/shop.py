import os
import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.main.db.db_transactions import get_shop_access_token
from src.main.db.db_models import User
from src.main.logging.logger import get_logger

logger = get_logger(__name__)

async def fetch_shop_locales(db: Session, shop_domain: str):
    """
    Core logic to fetch enabled locales for a shop from Shopify.
    Includes the merchant's current plan name for feature gating.
    """
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    # 1. Fetch User and Plan
    user = db.query(User).filter(User.username == shop_domain).first()
    plan_name = user.plan.name if user and user.plan else "Free"

    access_token = get_shop_access_token(db, shop_domain)
    if not access_token:
        raise HTTPException(status_code=401, detail="Shop not authenticated")

    graphql_query = """
    {
      shopLocales {
        locale
        name
        primary
        published
      }
    }
    """
    
    shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    graphql_url = f"https://{shop_domain}/admin/api/{shopify_api_version}/graphql.json"
    
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(graphql_url, headers=headers, json={"query": graphql_query})
            response.raise_for_status()
            
            data = response.json()
            if "errors" in data:
                 logger.error(f"GraphQL Errors: {data['errors']}")
                 raise HTTPException(status_code=500, detail="Shopify GraphQL Error")
            
            locales = data.get("data", {}).get("shopLocales", [])
            return {
                "status": "success", 
                "locales": locales,
                "plan_name": plan_name
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"Shopify GraphQL Request Failed: {e.response.text}")
        raise HTTPException(status_code=500, detail="Failed to fetch locales from Shopify")
    except Exception as e:
        logger.error(f"Unexpected error fetching locales: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


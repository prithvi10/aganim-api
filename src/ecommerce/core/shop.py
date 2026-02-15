import os
import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.ecommerce.db.transactions import get_shop_access_token
from src.ecommerce.db.models import User
from src.shared.logging.logger import get_logger
from src.shared.utils.httpx_verify import ssl_verify_shopify

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
    plan_name = user.plan.name if user and user.plan else "Basic"

    access_token = get_shop_access_token(db, shop_domain)
    if not access_token:
        raise HTTPException(status_code=401, detail="Shop not authenticated")

    token_preview = access_token[:5] + "..." if access_token else "None"
    logger.info(f"Fetching locales for {shop_domain} using token: {token_preview}")

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
        async with httpx.AsyncClient(verify=ssl_verify_shopify()) as client:
            response = await client.post(graphql_url, headers=headers, json={"query": graphql_query})
            response.raise_for_status()
            
            data = response.json()
            if "errors" in data:
                 error_msg = str(data['errors'])
                 logger.error(f"GraphQL Errors: {error_msg}")
                 if "Invalid API key or access token" in error_msg:
                     raise HTTPException(status_code=401, detail="Invalid Shopify Access Token")
                 raise HTTPException(status_code=500, detail="Shopify GraphQL Error")
            
            locales = data.get("data", {}).get("shopLocales", [])
            return {
                "status": "success", 
                "locales": locales,
                "plan_name": plan_name
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"Shopify GraphQL Request Failed: {e.response.text}")
        # Detect Invalid API Key error explicitly
        if "Invalid API key or access token" in e.response.text:
            token_type_log = "online" if access_token.startswith("shpua_") else "offline"
            logger.error(f"Authentication failed for {shop_domain}. Triggering re-auth. (Failed Token Type: {token_type_log})")
            raise HTTPException(status_code=401, detail="Invalid Shopify Access Token")
        raise HTTPException(status_code=500, detail="Failed to fetch locales from Shopify")
    except Exception as e:
        # Also catch it if it came from the generic Exception block (though raise_for_status handles 4xx/5xx)
        if "Invalid API key or access token" in str(e):
             token_type_log = "online" if access_token.startswith("shpua_") else "offline"
             logger.error(f"Authentication failed (Exception) for {shop_domain}. (Failed Token Type: {token_type_log})")
             raise HTTPException(status_code=401, detail="Invalid Shopify Access Token")
        logger.error(f"Unexpected error fetching locales: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


import os
import jwt  # pip install pyjwt
from fastapi import Header, HTTPException, Depends
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

# 1. Configuration
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET")
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")

#Verification Logic
#   Security (HMAC/JWT): To prove the request actually came from a paying Shopify merchant (and not a hacker).
#   Shopify sends a "Session Token" (JWT) with every request. 
#   Your Python backend must verify this token using your App Secret.

def verify_shopify_session(authorization: str = Header(...)):
    """
    Dependency to verify the Shopify Session Token (JWT).
    Usage: async def endpoint(shop: str = Depends(verify_shopify_session))
    
    Returns:
        str: The shop domain (e.g., 'my-store.myshopify.com') if valid.
    """
    print(f"Authorization: {authorization}")
    # 1. Sanity Check: Ensure secrets exist
    if not SHOPIFY_API_SECRET or not SHOPIFY_API_KEY:
        raise HTTPException(
            status_code=500, 
            detail="Server Misconfiguration: Missing Shopify API Credentials"
        )

    # 2. Parse the Header
    # Format should be: "Bearer <token_string>"
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    token = authorization.split(" ")[1]

    # DEV BYPASS: Allow a specific magic token for local testing
    if token == "dev-token-123":
        return "dev-shop.myshopify.com"

    try:
        # 3. Decode & Verify the JWT
        # - We use the 'HS256' algorithm (standard for Shopify).
        # - We verify the signature using your App Secret (only you and Shopify know this).
        # - We verify the 'audience' matches your specific App API Key (prevents token reuse).
        payload = jwt.decode(
            token, 
            SHOPIFY_API_SECRET, 
            algorithms=["HS256"], 
            audience=SHOPIFY_API_KEY
        )

        # 4. Extract the Shop Domain
        # The payload 'dest' field contains the shop URL (e.g., https://store.myshopify.com)
        dest = payload.get("dest")
        if not dest:
            raise HTTPException(status_code=401, detail="Invalid token payload: missing 'dest'")

        # Clean the URL to just the domain (remove https://)
        shop_domain = dest.replace("https://", "").replace("http://", "")
        
        return shop_domain

    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired. Please refresh the page.")
    except jwt.InvalidTokenError as e:
        print(f"⚠️ Security Alert: Invalid Token Attempt: {e}")
        raise HTTPException(status_code=401, detail="Invalid Shopify Token")
    except Exception as e:
        print(f"⚠️ Unknown Security Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Authentication Error")
"""
Shared utilities for Shopify API routes.

Contains common dependencies, helpers, and constants used across all Shopify routes.
"""

import os
import jwt
from typing import Optional
from fastapi import Request, HTTPException

from src.main.security.security import (
    verify_shopify_session,
    verify_shopify_proxy_request,
    SHOPIFY_API_KEY,
    SHOPIFY_API_SECRET,
)

# =============================================================================
# Constants
# =============================================================================

SCOPES = "read_products,write_products,read_locales,read_translations,write_translations,read_files"
SHOPIFY_REDIRECT_URI = "https://shopify-translator-api.onrender.com/api/auth/callback"
TOKEN_SYNC_SECRET = os.getenv("TOKEN_SYNC_SECRET")


# =============================================================================
# Shared Dependencies
# =============================================================================

async def resolve_shop_domain(request: Request) -> str:
    """
    Determine the shop for both Theme App Proxy and Admin UI Extensions.
    
    - Theme App Proxy: verify Shopify proxy signature (HMAC) on the full Request
    - Admin UI Extensions: verify Shopify session token (JWT) from Authorization header
    
    IMPORTANT:
    - `verify_shopify_session()` already returns a shop domain string (not a payload dict)
    - `verify_shopify_proxy_request()` expects the full FastAPI Request
    """
    auth_header = request.headers.get("Authorization") or ""

    # Path A: Admin Action / embedded app call (JWT)
    if auth_header.startswith("Bearer "):
        try:
            return verify_shopify_session(auth_header)
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid Admin Token")

    # Path B: Theme App Proxy (HMAC)
    try:
        return await verify_shopify_proxy_request(request)
    except HTTPException:
        raise


def get_request_id(request: Optional[Request]) -> str:
    """
    Extract request ID from request state for tracing.
    
    Returns "-" if request ID is not available.
    """
    try:
        return str(getattr(getattr(request, "state", None), "request_id", "") or "-")
    except Exception:
        return "-"


# Alias for backward compatibility
_rid = get_request_id

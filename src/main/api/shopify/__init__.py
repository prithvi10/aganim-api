"""
Shopify API Routes

Combines all Shopify-related route modules into a single router.
"""

from fastapi import APIRouter

from .oauth import router as oauth_router
from .proxy import router as proxy_router
from .admin import router as admin_router
from .webhooks import router as webhooks_router
from .missions import router as missions_router

# Combined router for all Shopify endpoints
shopify_router = APIRouter()

# Include all sub-routers
shopify_router.include_router(oauth_router)
shopify_router.include_router(proxy_router)
shopify_router.include_router(admin_router)
shopify_router.include_router(webhooks_router)
shopify_router.include_router(missions_router)

__all__ = ["shopify_router"]

"""
API Controller - Main router combining all platform-specific routes.

This module serves as the entry point that combines all route modules.
Each platform (Shopify, Shopee) has its own subfolder with specialized routes.

Structure:
    api/
    ├── controller.py       # This file - combines all routers
    ├── models.py           # Shared Pydantic models
    ├── validation.py       # Shared validation utilities
    │
    ├── shopify/            # Shopify-specific routes
    │   ├── oauth.py        # OAuth, callback, token sync
    │   ├── proxy.py        # App proxy, admin extension endpoints
    │   ├── admin.py        # Usage, brand context, onboarding
    │   ├── webhooks.py     # Subscription, compliance, install/uninstall
    │   └── missions.py     # Mission control, SSE streaming, corrections
    │
    └── shopee/             # Shopee-specific routes (future)
        └── __init__.py     # Empty placeholder
"""

from fastapi import APIRouter

# Import platform-specific routers
from .shopify import shopify_router
from .shopee import shopee_router

# Import shared utilities for backward compatibility
from .shopify.shared import resolve_shop_domain, get_request_id, _rid

# Backward compatibility: expose record_successful_rewrite as increment_monthly_rewrites_used
from src.main.db.db_transactions import record_successful_rewrite
increment_monthly_rewrites_used = record_successful_rewrite

# =============================================================================
# Main Router
# =============================================================================

router = APIRouter()

# Include Shopify routes (primary platform)
router.include_router(shopify_router)

# Include Shopee routes (future expansion)
router.include_router(shopee_router)


# =============================================================================
# Exports for backward compatibility
# =============================================================================

__all__ = [
    "router",
    "resolve_shop_domain",
    "get_request_id",
    "_rid",
    "increment_monthly_rewrites_used",
]

"""
SuperAdmin API — internal admin portal endpoints.

All routes are prefixed with /api/superadmin by the main controller.
"""
from fastapi import APIRouter

from .auth import router as auth_router
from .dashboard import router as dashboard_router
from .merchants import router as merchants_router
from .missions import router as missions_router
from .concerns import router as concerns_router
from .outreach import router as outreach_router

superadmin_router = APIRouter()

superadmin_router.include_router(auth_router)
superadmin_router.include_router(dashboard_router)
superadmin_router.include_router(merchants_router)
superadmin_router.include_router(missions_router)
superadmin_router.include_router(concerns_router)
superadmin_router.include_router(outreach_router)

__all__ = ["superadmin_router"]

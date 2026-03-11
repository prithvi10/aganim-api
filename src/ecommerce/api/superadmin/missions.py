"""
SuperAdmin mission monitoring & recovery endpoints.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import Mission, Shop
from .auth import verify_admin_token

router = APIRouter(dependencies=[Depends(verify_admin_token)])

STUCK_THRESHOLD_MINUTES = 10


@router.get("/missions")
async def list_missions(
    status: str = Query("", description="Filter by status"),
    shop: str = Query("", description="Filter by shop domain"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(Mission)

    if status:
        q = q.filter(Mission.status == status.upper())
    if shop:
        q = q.filter(Mission.tenant_id.ilike(f"%{shop}%"))

    total = q.count()
    missions = (
        q.order_by(Mission.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "missions": [
            {
                "id": m.id,
                "shop_domain": m.tenant_id,
                "resource_id": m.resource_id,
                "status": m.status,
                "tier": m.tier,
                "error_message": m.error_message,
                "created_at": str(m.created_at) if m.created_at else None,
                "updated_at": str(m.updated_at) if m.updated_at else None,
                "completed_at": str(m.completed_at) if m.completed_at else None,
            }
            for m in missions
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/missions/stuck")
async def stuck_missions(db: Session = Depends(get_db)):
    threshold = datetime.now(timezone.utc) - timedelta(minutes=STUCK_THRESHOLD_MINUTES)

    stuck = (
        db.query(Mission)
        .filter(
            Mission.status.in_(["IN_PROGRESS", "ERROR"]),
            Mission.updated_at < threshold,
        )
        .order_by(Mission.updated_at.asc())
        .all()
    )

    return {
        "stuck_missions": [
            {
                "id": m.id,
                "shop_domain": m.tenant_id,
                "resource_id": m.resource_id,
                "status": m.status,
                "tier": m.tier,
                "error_message": m.error_message,
                "created_at": str(m.created_at) if m.created_at else None,
                "updated_at": str(m.updated_at) if m.updated_at else None,
            }
            for m in stuck
        ],
        "count": len(stuck),
        "threshold_minutes": STUCK_THRESHOLD_MINUTES,
    }


@router.post("/missions/{mission_id}/recover")
async def recover_mission(
    mission_id: str,
    db: Session = Depends(get_db),
):
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    if mission.status not in ("IN_PROGRESS", "ERROR"):
        raise HTTPException(
            status_code=400,
            detail=f"Mission is in '{mission.status}' state; only IN_PROGRESS or ERROR missions can be recovered",
        )

    old_status = mission.status
    mission.status = "PENDING"
    mission.error_message = None
    mission.updated_at = datetime.now(timezone.utc)
    db.add(mission)
    db.commit()

    return {
        "mission_id": mission_id,
        "previous_status": old_status,
        "new_status": "PENDING",
        "message": "Mission has been reset and can be retried",
    }

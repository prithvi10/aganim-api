"""
Generic Mission CRUD Router for the agentic_core.

This router defines the domain-agnostic API surface for mission management.
When the agentic_core is extracted as a standalone microservice, this becomes
the primary FastAPI app.

The Shopify ecommerce layer wraps these operations by adding authentication,
resolving ``shop_domain`` to ``tenant_id``, and injecting domain-specific
callbacks (cost_recorder, publish_adapter, etc.).
"""

import json
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.shared.logging.logger import get_logger
from src.agentic_core.api.models import (
    CreateMissionRequest,
    MissionResponse,
    StepResponse,
    AdvanceRequest,
    RegenerateRequest,
    SkipRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/missions", tags=["missions"])


# ---------------------------------------------------------------------------
# Lazy imports to avoid circular dependencies
# ---------------------------------------------------------------------------

def _get_mission_model():
    from src.agentic_core.db.models import Mission
    return Mission


def _get_mission_control():
    from src.agentic_core.agents.orchestrator import MissionControl
    return MissionControl


def _get_mission_state():
    from src.agentic_core.agents.state import GenericMissionState
    return GenericMissionState


# ---------------------------------------------------------------------------
# CRUD Endpoints
# ---------------------------------------------------------------------------

async def create_mission(
    req: CreateMissionRequest,
    db: Session,
    *,
    services: Any = None,
    cost_recorder: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Create a new mission record in the database.

    This is a *function* (not a route handler) so the ecommerce layer can
    call it after adding its own auth/validation.
    """
    Mission = _get_mission_model()
    MissionControl = _get_mission_control()

    mission_id = uuid.uuid4().hex

    # Build initial state dict
    initial_state = {
        "product_id": req.resource_id,
        "shop_id": req.tenant_id,
        "plan_tier": req.tier,
        "raw_input": req.raw_input,
        "status": "PENDING",
        "logs": [],
        "requested_agents": req.requested_agents,
        "is_adhoc": bool(req.requested_agents),
        "current_agent_index": 0,
        "skipped_agents": [],
        "agent_outputs": {},
        "workflow_config": req.workflow_config or [],
    }

    # Determine workflow agents if services provided
    workflow_agents = []
    if services:
        mc = MissionControl(
            plan_tier=req.tier,
            shop_id=req.tenant_id,
            services=services,
            requested_agents=req.requested_agents,
            workflow_config=req.workflow_config,
            cost_recorder=cost_recorder,
        )
        workflow_agents = [a.__name__ for a in mc.workflow]

    initial_state["workflow_agents"] = workflow_agents

    mission = Mission(
        id=mission_id,
        tenant_id=req.tenant_id,
        resource_id=req.resource_id,
        status="PENDING",
        current_state=initial_state,
        logs=[],
        tier=req.tier,
    )

    db.add(mission)
    db.commit()

    logger.info(
        "[Mission] created mission_id=%s tenant=%s resource=%s tier=%s",
        mission_id, req.tenant_id, req.resource_id, req.tier,
    )

    return {
        "status": "created",
        "mission_id": mission_id,
        "workflow_agents": workflow_agents,
        "total_agents": len(workflow_agents),
        "current_agent_index": 0,
        "first_agent": workflow_agents[0] if workflow_agents else None,
    }


async def get_mission(
    mission_id: str,
    db: Session,
    tenant_id: str,
) -> Dict[str, Any]:
    """Fetch a single mission by ID, scoped to tenant."""
    Mission = _get_mission_model()

    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.tenant_id == tenant_id,
    ).first()

    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    return {
        "mission_id": mission.id,
        "tenant_id": mission.tenant_id,
        "resource_id": mission.resource_id,
        "status": mission.status,
        "tier": mission.tier,
        "current_state": mission.current_state,
        "logs": mission.logs,
        "error_message": mission.error_message,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
    }


async def list_missions(
    db: Session,
    tenant_id: str,
    limit: int = 10,
) -> Dict[str, Any]:
    """List missions for a tenant, ordered by created_at descending."""
    Mission = _get_mission_model()

    all_missions = (
        db.query(Mission)
        .filter(Mission.tenant_id == tenant_id)
        .order_by(Mission.created_at.desc())
        .limit(limit * 2)
        .all()
    )

    # Filter out ad-hoc missions
    missions = [
        m for m in all_missions
        if not (m.current_state or {}).get("is_adhoc", False)
    ][:limit]

    return {
        "missions": [
            {
                "id": m.id,
                "resource_id": m.resource_id,
                "status": m.status,
                "tier": m.tier,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "completed_at": m.completed_at.isoformat() if m.completed_at else None,
                "error_message": m.error_message,
            }
            for m in missions
        ],
        "latest": missions[0].id if missions else None,
    }

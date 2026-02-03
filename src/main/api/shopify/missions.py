"""
Shopify Mission Routes

Handles agentic architecture endpoints including SSE streaming, mission control,
and user correction/feedback endpoints.
"""

import json
import asyncio
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.main.api.models import MissionRequest, CorrectionRequest
from src.main.db.database import get_db
from src.main.api.validation import validate_shop_and_quota
from src.main.logging.logger import get_logger

from .shared import resolve_shop_domain, _rid

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Mission Endpoints
# =============================================================================

@router.options("/api/missions")
async def missions_preflight():
    return Response(status_code=204)


@router.post("/api/missions")
async def create_mission(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Create a new agent mission and return a mission ID.
    
    The client should then connect to /api/missions/{mission_id}/stream
    to receive real-time updates via SSE.
    """
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        logger.info("[Mission] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    try:
        mission_req = MissionRequest(**body)
    except ValidationError as e:
        logger.info("[Mission] invalid_payload rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())
    
    # Validate shop and get plan tier
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=True)
    plan = auth_context["plan"]
    plan_tier = getattr(plan, "name", "Basic")
    
    # Create mission record in database
    import uuid
    from datetime import datetime, timezone
    from src.main.db.db_models import Mission
    
    mission_id = uuid.uuid4().hex
    
    # Determine if this is an ad-hoc run with specific agents
    requested_agents = mission_req.requested_agents
    is_adhoc = requested_agents is not None and len(requested_agents) > 0
    
    initial_state = {
        "product_id": mission_req.product_id,
        "shop_id": shop,
        "plan_tier": plan_tier,
        "raw_input": {
            "product_id": mission_req.product_id,
            "title": mission_req.product_name,
            "product_name": mission_req.product_name,
            "description": mission_req.japanese_description,
            "japanese_description": mission_req.japanese_description,
            "category": mission_req.category,
            "tone": mission_req.tone_profile,
            "target_locale": mission_req.target_locale,
            "brand_soul_enabled": mission_req.brand_soul_enabled,
        },
        "target_locale": mission_req.target_locale,
        "status": "PENDING",
        "logs": [],
        # Ad-hoc agent selection
        "requested_agents": requested_agents,
        "is_adhoc": is_adhoc,
    }
    
    mission = Mission(
        id=mission_id,
        shop_id=shop,
        product_id=mission_req.product_id,
        status="PENDING",
        current_state=initial_state,
        logs=[],
        plan_tier=plan_tier,
    )
    
    db.add(mission)
    db.commit()
    
    logger.info(
        "[Mission] created rid=%s shop=%s mission_id=%s product_id=%s plan=%s adhoc=%s agents=%s",
        rid, shop, mission_id, mission_req.product_id, plan_tier, is_adhoc, requested_agents,
    )
    
    return {
        "status": "created",
        "mission_id": mission_id,
        "stream_url": f"/api/missions/{mission_id}/stream",
        "is_adhoc": is_adhoc,
        "requested_agents": requested_agents,
    }


@router.get("/api/missions/{mission_id}/stream")
async def stream_mission(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    SSE endpoint for streaming agent mission updates.
    
    Events:
    - event: state_update -> Mission state changed
    - event: agent_start -> An agent started working
    - event: agent_complete -> An agent finished
    - event: complete -> Mission finished
    - event: error -> Error occurred
    """
    rid = _rid(request)
    
    # Verify mission belongs to this shop
    from src.main.db.db_models import Mission
    
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    logger.info("[MissionStream] start rid=%s shop=%s mission_id=%s", rid, shop, mission_id)
    
    async def event_generator():
        """Generate SSE events as agents complete."""
        from src.main.agents import MissionControl, MissionState
        from src.main.services import ServiceRegistry
        
        # Load initial state from mission record
        initial_state_dict = mission.current_state or {}
        
        state = MissionState.from_dict(initial_state_dict, db=db)
        
        # Create services and mission control
        services = ServiceRegistry.create_default()
        plan_tier = mission.plan_tier or "Basic"
        
        # Check for ad-hoc agent selection
        requested_agents = initial_state_dict.get("requested_agents")
        
        mission_control = MissionControl(
            plan_tier=plan_tier,
            shop_id=shop,
            services=services,
            requested_agents=requested_agents,
        )
        
        try:
            # Execute workflow and yield events
            async for updated_state in mission_control.execute(state):
                # Update mission record in DB
                try:
                    mission.current_state = updated_state.to_dict()
                    mission.status = updated_state.status
                    mission.logs = updated_state.logs
                    if updated_state.status in ("COMPLETED", "ERROR"):
                        from datetime import datetime, timezone
                        mission.completed_at = datetime.now(timezone.utc)
                    if updated_state.error_message:
                        mission.error_message = updated_state.error_message
                    db.add(mission)
                    db.commit()
                except Exception as e:
                    logger.warning("[MissionStream] DB update failed: %s", e)
                    try:
                        db.rollback()
                    except Exception:
                        pass
                
                # Yield SSE event
                state_json = json.dumps(updated_state.to_dict())
                yield f"event: state_update\ndata: {state_json}\n\n"
                
                # Small delay to prevent overwhelming the client
                await asyncio.sleep(0.1)
            
            # Final completion event
            yield f"event: complete\ndata: {json.dumps({'mission_id': mission_id, 'status': state.status})}\n\n"
            
        except Exception as e:
            logger.exception("[MissionStream] Error in mission %s", mission_id)
            error_data = json.dumps({"error": str(e), "mission_id": mission_id})
            yield f"event: error\ndata: {error_data}\n\n"
            
            # Update mission with error status
            try:
                mission.status = "ERROR"
                mission.error_message = str(e)
                db.add(mission)
                db.commit()
            except Exception:
                pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/api/missions/{mission_id}")
async def get_mission(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Get the current state of a mission.
    """
    from src.main.db.db_models import Mission
    
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    return {
        "mission_id": mission.id,
        "shop_id": mission.shop_id,
        "product_id": mission.product_id,
        "status": mission.status,
        "plan_tier": mission.plan_tier,
        "current_state": mission.current_state,
        "logs": mission.logs,
        "error_message": mission.error_message,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
    }


# =============================================================================
# Correction Endpoints
# =============================================================================

@router.options("/api/corrections")
async def corrections_preflight():
    return Response(status_code=204)


@router.post("/api/corrections")
async def submit_correction(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Submit a user correction for agent learning.
    
    When users edit AI-generated content, this endpoint stores
    the correction so agents can learn from it in future runs.
    """
    rid = _rid(request)
    try:
        body = await request.json()
    except Exception:
        logger.info("[Correction] invalid_json rid=%s", rid)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    try:
        correction_req = CorrectionRequest(**body)
    except ValidationError as e:
        logger.info("[Correction] invalid_payload rid=%s errors=%s", rid, e.errors())
        raise HTTPException(status_code=422, detail=e.errors())
    
    # Store correction in database
    import uuid
    from src.main.db.db_models import AgentCorrection
    
    correction_id = uuid.uuid4().hex
    
    # Generate embedding for the correction (for future similarity search)
    embedding = None
    try:
        from src.main.rag.embedding.embedding import embed_texts
        correction_text = f"{correction_req.original_output}\n---\n{correction_req.user_correction}"
        embeddings = embed_texts([correction_text])
        if embeddings:
            embedding = embeddings[0]
    except Exception as e:
        logger.warning("[Correction] Embedding generation failed: %s", e)
    
    correction = AgentCorrection(
        id=correction_id,
        shop_id=shop,
        agent_role=correction_req.agent_role,
        original_output=correction_req.original_output,
        user_correction=correction_req.user_correction,
        embedding=embedding,
        product_id=correction_req.product_id,
        context_metadata=correction_req.context_metadata,
    )
    
    db.add(correction)
    db.commit()
    
    logger.info(
        "[Correction] saved rid=%s shop=%s correction_id=%s agent=%s product=%s",
        rid, shop, correction_id, correction_req.agent_role, correction_req.product_id,
    )
    
    return {
        "status": "success",
        "correction_id": correction_id,
        "message": "Correction saved for future learning",
    }


@router.get("/api/corrections")
async def list_corrections(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
    agent_role: str = Query(None, description="Filter by agent role"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    List corrections submitted by this shop.
    """
    from src.main.db.db_models import AgentCorrection
    
    query = db.query(AgentCorrection).filter(AgentCorrection.shop_id == shop)
    
    if agent_role:
        query = query.filter(AgentCorrection.agent_role == agent_role)
    
    corrections = query.order_by(AgentCorrection.created_at.desc()).limit(limit).all()
    
    return {
        "corrections": [
            {
                "id": c.id,
                "agent_role": c.agent_role,
                "original_output": c.original_output[:200] + "..." if len(c.original_output) > 200 else c.original_output,
                "user_correction": c.user_correction[:200] + "..." if len(c.user_correction) > 200 else c.user_correction,
                "product_id": c.product_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in corrections
        ],
        "count": len(corrections),
    }

"""
Shopify Mission Routes

Handles agentic architecture endpoints including SSE streaming, mission control,
and user correction/feedback endpoints.
"""
from __future__ import annotations

import json
import os
import asyncio
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.ecommerce.api.models import (
    MissionRequest,
    BulkMissionRequest,
    CorrectionRequest,
    RegenerateRequest,
    StepResponse,
    MissionStatusResponse,
)
from src.shared.db.database import get_db
from src.ecommerce.api.validation import (
    validate_shop_and_quota,
    validate_mission_access,
    validate_feature_access,
    validate_image_credits,
)
from src.ecommerce.plans.entitlements import get_entitlements
from src.shared.logging.logger import get_logger

from .shared import resolve_shop_domain, _rid

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Mission Endpoints
# =============================================================================

@router.options("/api/missions")
async def missions_preflight():
    return Response(status_code=204)


@router.get("/api/missions")
async def list_missions(
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
    limit: int = Query(default=10, le=50),
):
    """
    List missions for a shop, ordered by created_at descending.
    
    Returns recent missions with their status and basic info.
    The 'latest' field indicates the most recent mission ID.
    
    Note: Ad-hoc missions (is_adhoc=True) are filtered out as they are
    lightweight single-agent runs that shouldn't clutter mission history.
    """
    from src.ecommerce.db.models import Mission
    
    rid = _rid(request)
    logger.info("[MissionList] rid=%s shop=%s limit=%d", rid, shop, limit)
    
    all_missions = db.query(Mission).filter(
        Mission.shop_id == shop,
        Mission.bulk_mission_id.is_(None),  # exclude bulk children at DB level
    ).order_by(Mission.created_at.desc()).limit(limit * 3).all()

    # Filter out ad-hoc missions (stored in JSON, must filter in Python)
    missions = [
        m for m in all_missions
        if not (m.current_state or {}).get("is_adhoc", False)
    ][:limit]
    
    return {
        "missions": [
            {
                "id": m.id,
                "product_id": m.product_id,
                "status": m.status,
                "plan_tier": m.plan_tier,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "completed_at": m.completed_at.isoformat() if m.completed_at else None,
                "error_message": m.error_message,
                # Extract product name from current_state if available
                "product_name": (m.current_state or {}).get("raw_input", {}).get("product_name"),
                # Mission title: preset name or agent names (set by wizard via extra_context)
                "mission_title": (m.current_state or {}).get("raw_input", {}).get("mission_title"),
                # Bulk parent flag for UI routing
                "is_bulk_parent": bool((m.current_state or {}).get("is_bulk_parent")),
            }
            for m in missions
        ],
        "latest": missions[0].id if missions else None,
    }


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
    
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=True)

    _IMAGE_ONLY_AGENTS = {"VisualMarketingAgent", "ImageRefinementAgent"}
    workflow_agents = set()
    if mission_req.workflow_config:
        for step in mission_req.workflow_config:
            name = step.get("agent_name") if isinstance(step, dict) else getattr(step, "agent_name", None)
            if name:
                workflow_agents.add(name)

    is_image_only_adhoc = bool(workflow_agents) and workflow_agents.issubset(_IMAGE_ONLY_AGENTS)

    if is_image_only_adhoc:
        validate_image_credits(auth_context)
    else:
        validate_mission_access(auth_context)

    plan = auth_context["plan"]
    plan_tier = getattr(plan, "name", "Basic")
    shop_obj = auth_context["shop"]

    if not is_image_only_adhoc:
        ent = get_entitlements(plan_tier)
        if ent.get("mission_limit_type") == "lifetime":
            shop_obj.lifetime_missions_remaining = max(0, int(getattr(shop_obj, "lifetime_missions_remaining", 0) or 0) - 1)
        else:
            shop_obj.monthly_missions_used = int(getattr(shop_obj, "monthly_missions_used", 0) or 0) + 1
        db.add(shop_obj)
        db.commit()
        db.refresh(shop_obj)

    import uuid
    from datetime import datetime, timezone
    from src.ecommerce.db.models import Mission
    
    mission_id = uuid.uuid4().hex
    
    # Determine if this is an ad-hoc run with specific agents
    requested_agents = mission_req.requested_agents
    is_adhoc = requested_agents is not None and len(requested_agents) > 0
    
    # Mission Architect workflow_config takes priority
    workflow_config = mission_req.workflow_config
    
    # Determine workflow agents based on workflow_config, ad-hoc selection, or tier
    from src.ecommerce.orchestrator import MissionControl
    from src.ecommerce.services import ServiceRegistry
    
    temp_services = ServiceRegistry.create_default(db=db, shop_domain=shop)
    temp_mission_control = MissionControl(
        plan_tier=plan_tier,
        shop_id=shop,
        services=temp_services,
        requested_agents=requested_agents,
        workflow_config=workflow_config,
    )
    workflow_agents = [a.__name__ for a in temp_mission_control.workflow]
    
    # Build raw_input — base product fields + any extra wizard context
    raw_input = {
            "product_id": mission_req.product_id,
            "title": mission_req.product_name,
            "product_name": mission_req.product_name,
            "description": mission_req.japanese_description,
            "japanese_description": mission_req.japanese_description,
            "category": mission_req.category,
            "tone": mission_req.tone_profile,
            "target_locale": mission_req.target_locale,
            "brand_soul_enabled": bool(auth_context.get("brand_soul_enabled", True)),
            "refinement_theme": getattr(mission_req, "refinement_theme", "clean"),
            "brand_name": getattr(mission_req, "brand_name", "") or shop.split(".")[0].replace("-", " ").title(),
    }
    # Include product image URL for VisualAgent
    if mission_req.image_url:
        raw_input["image_url"] = mission_req.image_url

    # Fallback: if VisualAgent is in the pipeline but no image_url was provided,
    # fetch the product's featured image from Shopify directly.
    if not raw_input.get("image_url") and "VisualAgent" in workflow_agents:
        try:
            from src.ecommerce.db.transactions import get_shop_access_token
            import httpx

            access_token = get_shop_access_token(db, shop)
            if access_token:
                product_gid = f"gid://shopify/Product/{mission_req.product_id}"
                gql_query = (
                    '{"query":"{ product(id: \\\"%s\\\") { featuredImage { url } } }"}'
                    % product_gid
                )
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"https://{shop}/admin/api/2024-10/graphql.json",
                        content=gql_query,
                        headers={
                            "X-Shopify-Access-Token": access_token,
                            "Content-Type": "application/json",
                        },
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        img_url = (
                            resp.json()
                            .get("data", {})
                            .get("product", {})
                            .get("featuredImage", {})
                            .get("url", "")
                        )
                        if img_url:
                            raw_input["image_url"] = img_url
                            logger.info(
                                "[Mission] fetched_image_fallback rid=%s shop=%s image_url=%s",
                                rid, shop, img_url[:120],
                            )
        except Exception as e:
            logger.warning(
                "[Mission] image_fallback_failed rid=%s shop=%s err=%s",
                rid, shop, str(e)[:200],
            )

    if mission_req.extra_context:
        raw_input.update(mission_req.extra_context)
    
    initial_state = {
        "product_id": mission_req.product_id,
        "shop_id": shop,
        "plan_tier": plan_tier,
        "raw_input": raw_input,
        "target_locale": mission_req.target_locale,
        "status": "PENDING",
        "logs": [],
        # Ad-hoc agent selection
        "requested_agents": requested_agents,
        "is_adhoc": is_adhoc,
        # Step-by-step journey tracking
        "current_agent_index": 0,
        "skipped_agents": [],
        "agent_outputs": {},
        "workflow_agents": workflow_agents,
        # Mission Architect pipeline config
        "workflow_config": workflow_config or [],
        # Autonomous execution (Pro tier)
        "autonomous": plan_tier == "Pro",
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
        "step_url": f"/api/missions/{mission_id}/run-step",
        "is_adhoc": is_adhoc,
        "requested_agents": requested_agents,
        # Step-by-step journey info
        "workflow_agents": workflow_agents,
        "total_agents": len(workflow_agents),
        "current_agent_index": 0,
        "first_agent": workflow_agents[0] if workflow_agents else None,
    }


# Simple in-memory lock to prevent concurrent mission execution
# In production, consider using Redis or database locks
_mission_locks: dict[str, bool] = {}

# Track retry counts to prevent infinite reconnection loops
_mission_retry_counts: dict[str, int] = {}
_MAX_STREAM_RETRIES = 3


@router.get("/api/missions/{mission_id}/stream")
async def stream_mission(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    SSE endpoint for streaming agent mission updates (auto-flow mode).
    
    NOTE: For step-by-step journey with merchant approval between agents,
    use /api/missions/{mission_id}/run-step instead.
    
    Events:
    - event: state_update -> Mission state changed
    - event: agent_start -> An agent started working
    - event: agent_complete -> An agent finished
    - event: complete -> Mission finished
    - event: error -> Error occurred
    
    This endpoint includes protection against reconnection loops:
    - Checks if mission is already running (status = IN_PROGRESS)
    - Uses in-memory lock to prevent concurrent execution
    - Already completed missions return cached result
    """
    rid = _rid(request)
    
    # Verify mission belongs to this shop
    from src.ecommerce.db.models import Mission
    
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    # Check if mission is already completed - return cached result
    if mission.status in ("COMPLETED", "ERROR", "COMPLIANCE_REVIEW"):
        logger.info(
            "[MissionStream] already_complete rid=%s mission_id=%s status=%s",
            rid, mission_id, mission.status,
        )
        
        async def completed_generator():
            """Return the final state for already-completed missions."""
            state_json = json.dumps(mission.current_state or {})
            yield f"event: state_update\ndata: {state_json}\n\n"
            yield f"event: complete\ndata: {json.dumps({'mission_id': mission_id, 'status': mission.status, 'already_complete': True})}\n\n"
        
        return StreamingResponse(
            completed_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    
    # Check if mission is currently being processed (prevents reconnection loops)
    # Only block if there's an active lock - IN_PROGRESS without lock means previous run was interrupted
    if _mission_locks.get(mission_id):
        logger.warning(
            "[MissionStream] mission_already_running rid=%s mission_id=%s status=%s",
            rid, mission_id, mission.status,
        )
        
        async def in_progress_generator():
            """Return error for already-running missions."""
            error_data = json.dumps({
                "error": "Mission already in progress",
                "mission_id": mission_id,
                "status": mission.status,
                "hint": "Wait for current execution to complete or check /api/missions/{id}/status"
            })
            yield f"event: error\ndata: {error_data}\n\n"
        
        return StreamingResponse(
            in_progress_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    
    # Reset stuck IN_PROGRESS missions (no lock held but status is IN_PROGRESS)
    # Cap retries to prevent infinite reconnection loops (e.g. from EventSource auto-reconnect)
    if mission.status == "IN_PROGRESS":
        retry_count = _mission_retry_counts.get(mission_id, 0) + 1
        _mission_retry_counts[mission_id] = retry_count

        if retry_count > _MAX_STREAM_RETRIES:
            logger.warning(
                "[MissionStream] max_retries_exceeded rid=%s mission_id=%s retries=%s — marking ERROR",
                rid, mission_id, retry_count,
            )
            mission.status = "ERROR"
            mission.error_message = "Mission execution exceeded maximum retries"
            db.add(mission)
            db.commit()
            # Fall through to the already-complete check above on next request
            async def retry_exceeded_gen():
                error_data = json.dumps({
                    "error": "Mission exceeded maximum retries",
                    "mission_id": mission_id,
                    "status": "ERROR",
                })
                yield f"event: error\ndata: {error_data}\n\n"
            return StreamingResponse(
                retry_exceeded_gen(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        logger.warning(
            "[MissionStream] resetting_stuck_mission rid=%s mission_id=%s from IN_PROGRESS to PENDING (retry %s/%s)",
            rid, mission_id, retry_count, _MAX_STREAM_RETRIES,
        )
        mission.status = "PENDING"
        db.add(mission)
        db.commit()
    
    logger.info("[MissionStream] start rid=%s shop=%s mission_id=%s", rid, shop, mission_id)
    
    async def event_generator():
        """Generate SSE events as agents complete."""
        from src.ecommerce.orchestrator import MissionControl, MissionState
        from src.ecommerce.services import ServiceRegistry
        
        # Acquire lock
        _mission_locks[mission_id] = True
        workflow_task = None
        
        try:
            # Load initial state from mission record
            initial_state_dict = mission.current_state or {}
            
            state = MissionState.from_dict(initial_state_dict, db=db)
            state.mission_id = mission_id
            
            # Create services and mission control (with db/shop for usage tracking)
            services = ServiceRegistry.create_default(db=db, shop_domain=shop)
            plan_tier = mission.plan_tier or "Basic"
            
            # Check for ad-hoc agent selection and workflow_config
            requested_agents = initial_state_dict.get("requested_agents")
            wf_config = initial_state_dict.get("workflow_config")
            
            mission_control = MissionControl(
                plan_tier=plan_tier,
                shop_id=shop,
                services=services,
                requested_agents=requested_agents,
                mission_id=mission_id,  # Pass DB mission_id to ensure consistent logging
                workflow_config=wf_config,
            )
            
            # Send initial heartbeat
            yield f": heartbeat\n\n"
            
            # Track the latest state from execute() for final event
            last_state = None

            # Run orchestrator in a background task so we can emit interim
            # progress snapshots every few seconds (critical for long-running
            # visual pipelines where a single agent may run for minutes).
            _PROGRESS_POLL_INTERVAL = 2.0  # seconds
            update_queue: asyncio.Queue = asyncio.Queue()

            async def _run_workflow():
                try:
                    async for s in mission_control.execute(state):
                        await update_queue.put(("state", s))
                    await update_queue.put(("done", None))
                except Exception as exc:
                    await update_queue.put(("error", exc))

            workflow_task = asyncio.create_task(_run_workflow())

            def _persist_state(s):
                """Write state snapshot to DB (best-effort)."""
                try:
                    mission.current_state = s.to_dict()
                    mission.status = s.status
                    mission.logs = s.logs
                    if s.status in ("COMPLETED", "ERROR"):
                        from datetime import datetime, timezone
                        mission.completed_at = datetime.now(timezone.utc)
                    if s.error_message:
                        mission.error_message = s.error_message
                    db.add(mission)
                    db.commit()
                except Exception as e:
                    logger.warning("[MissionStream] DB update failed: %s", e)
                    try:
                        db.rollback()
                    except Exception:
                        pass

            while True:
                try:
                    kind, payload = await asyncio.wait_for(
                        update_queue.get(), timeout=_PROGRESS_POLL_INTERVAL,
                    )
                except asyncio.TimeoutError:
                    # No orchestrator yield yet — emit interim state snapshot
                    # so the frontend sees visual_progress / visual_assets updates.
                    state_json = json.dumps(state.to_dict())
                    yield f"event: state_update\ndata: {state_json}\n\n"
                    yield f": heartbeat\n\n"
                    continue

                if kind == "done":
                    break
                if kind == "error":
                    raise payload

                updated_state = payload
                last_state = updated_state
                _persist_state(updated_state)

                state_json = json.dumps(updated_state.to_dict())
                yield f"event: state_update\ndata: {state_json}\n\n"
                yield f": heartbeat\n\n"
                await asyncio.sleep(0.1)

            # Ensure the task is awaited to surface any unhandled exceptions
            await workflow_task
            
            # Safety net: ensure mission is marked as terminal in DB.
            final_status = getattr(last_state, "status", "COMPLETED") if last_state else "COMPLETED"
            if final_status not in ("COMPLETED", "ERROR", "COMPLIANCE_REVIEW"):
                final_status = "COMPLETED"
            try:
                mission.status = final_status
                if not mission.completed_at:
                    from datetime import datetime, timezone
                    mission.completed_at = datetime.now(timezone.utc)
                db.add(mission)
                db.commit()
            except Exception:
                pass

            # Final completion event
            yield f"event: complete\ndata: {json.dumps({'mission_id': mission_id, 'status': final_status})}\n\n"
            
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
        
        finally:
            # Cancel the workflow task if it's still running (prevents orphaned
            # pipelines when the SSE connection drops mid-execution).
            if workflow_task and not workflow_task.done():
                workflow_task.cancel()
                logger.warning(
                    "[MissionStream] cancelled_orphan_workflow rid=%s mission_id=%s",
                    rid, mission_id,
                )
            # Always release the lock and clear retry counter on success
            _mission_locks.pop(mission_id, None)
            _mission_retry_counts.pop(mission_id, None)
            logger.info("[MissionStream] released_lock rid=%s mission_id=%s", rid, mission_id)
    
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
    from src.ecommerce.db.models import Mission
    
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
# Step-by-Step Journey Endpoints
# =============================================================================

@router.get("/api/missions/{mission_id}/status")
async def get_mission_status(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
) -> MissionStatusResponse:
    """
    Get detailed mission status for step-by-step journey UI.
    
    Returns structured info about current step, workflow progress, and agent outputs.
    """
    from src.ecommerce.db.models import Mission
    
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    state = mission.current_state or {}
    workflow_agents = state.get("workflow_agents", [])
    current_idx = state.get("current_agent_index", 0)
    
    # Determine current agent name
    current_agent = None
    if workflow_agents and current_idx < len(workflow_agents):
        current_agent = workflow_agents[current_idx]
    
    return MissionStatusResponse(
        mission_id=mission.id,
        shop_id=mission.shop_id,
        product_id=mission.product_id,
        status=mission.status,
        plan_tier=mission.plan_tier or "Basic",
        current_agent_index=current_idx,
        total_agents=len(workflow_agents),
        current_agent=current_agent,
        workflow_agents=workflow_agents,
        skipped_agents=state.get("skipped_agents", []),
        agent_outputs=state.get("agent_outputs", {}),
        logs=mission.logs or [],
        error_message=mission.error_message,
        created_at=mission.created_at.isoformat() if mission.created_at else None,
        completed_at=mission.completed_at.isoformat() if mission.completed_at else None,
        current_state=state,  # Include full state for resuming missions
    )


@router.get("/api/missions/{mission_id}/run-step")
async def run_step(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Run the current agent in the step-by-step workflow via SSE.
    
    NOTE: This is a GET endpoint because EventSource only supports GET requests.
    
    This endpoint runs only the current agent, then streams its output.
    After completion, the status will be AWAITING_APPROVAL for the merchant
    to decide whether to Continue, Regenerate, or Skip.
    """
    rid = _rid(request)
    from src.ecommerce.db.models import Mission
    
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    # Check lock FIRST to prevent concurrent execution
    if _mission_locks.get(mission_id):
        raise HTTPException(
            status_code=409,
            detail="Step already being executed - wait for completion"
        )
    
    # Check if mission is in a valid state to run a step
    if mission.status not in ("PENDING", "AWAITING_APPROVAL"):
        if mission.status == "IN_PROGRESS":
            # No lock held but status is IN_PROGRESS means previous run was interrupted
            # Reset to AWAITING_APPROVAL so the step can be re-run
            logger.warning(
                "[MissionStep] resetting_stuck_mission rid=%s mission_id=%s from IN_PROGRESS to AWAITING_APPROVAL",
                rid, mission_id
            )
            mission.status = "AWAITING_APPROVAL"
            db.add(mission)
            db.commit()
            # Continue to run the step
        elif mission.status == "COMPLETED":
            raise HTTPException(status_code=400, detail="Mission already completed")
        elif mission.status == "ERROR":
            raise HTTPException(status_code=400, detail="Mission in error state")
    
    logger.info("[MissionStep] run-step rid=%s shop=%s mission_id=%s", rid, shop, mission_id)
    
    async def event_generator():
        """Generate SSE events for single agent execution."""
        from src.ecommerce.orchestrator import MissionControl, MissionState
        from src.ecommerce.services import ServiceRegistry
        
        # Acquire lock
        _mission_locks[mission_id] = True
        
        try:
            # Load state from mission record
            state_dict = mission.current_state or {}
            state = MissionState.from_dict(state_dict, db=db)
            state.mission_id = mission_id
            
            # Create services and mission control (with db/shop for usage tracking)
            services = ServiceRegistry.create_default(db=db, shop_domain=shop)
            plan_tier = mission.plan_tier or "Basic"
            requested_agents = state_dict.get("requested_agents")
            wf_config = state_dict.get("workflow_config")
            
            mission_control = MissionControl(
                plan_tier=plan_tier,
                shop_id=shop,
                services=services,
                requested_agents=requested_agents,
                mission_id=mission_id,  # Pass DB mission_id for consistent logging
                workflow_config=wf_config,
            )
            _STEP_POLL_INTERVAL = 2.0

            def _persist_step_state(s: MissionState):
                try:
                    mission.current_state = s.to_dict()
                    mission.status = s.status
                    mission.logs = s.logs
                    if s.status == "COMPLETED":
                        from datetime import datetime, timezone
                        mission.completed_at = datetime.now(timezone.utc)
                    if s.error_message:
                        mission.error_message = s.error_message
                    db.add(mission)
                    db.commit()
                except Exception as e:
                    logger.warning("[MissionStep] DB update failed: %s", e)
                    try:
                        db.rollback()
                    except Exception:
                        pass

            # Execute single step with interim state polling so that
            # long-running visual agents can surface images incrementally.
            while True:
                step_queue: asyncio.Queue = asyncio.Queue()

                async def _run_step():
                    async for updated_state in mission_control.execute_single_step(state):
                        await step_queue.put(("state", updated_state))
                    await step_queue.put(("done", None))

                step_task = asyncio.create_task(_run_step())

                try:
                    while True:
                        try:
                            kind, payload = await asyncio.wait_for(
                                step_queue.get(), timeout=_STEP_POLL_INTERVAL,
                            )
                        except asyncio.TimeoutError:
                            # Emit interim state snapshot (visual_assets / visual_progress)
                            state_json = json.dumps(state.to_dict())
                            yield f"event: state_update\ndata: {state_json}\n\n"
                            yield f": heartbeat\n\n"
                            continue

                        if kind == "done":
                            break

                        updated_state = payload
                        _persist_step_state(updated_state)

                        state_json = json.dumps(updated_state.to_dict())
                        yield f"event: state_update\ndata: {state_json}\n\n"

                        state = updated_state
                        await asyncio.sleep(0.1)

                    await step_task
                finally:
                    if step_task and not step_task.done():
                        step_task.cancel()

                # Check if auto-proceeded (status PENDING means no gate, keep running)
                if state.status == "PENDING" and state.current_agent_index < len(mission_control.workflow):
                    auto_data = {
                        "mission_id": mission_id,
                        "auto_proceeded_from": state.current_agent_index - 1,
                        "next_agent_index": state.current_agent_index,
                        "next_agent": state.workflow_agents[state.current_agent_index] if state.current_agent_index < len(state.workflow_agents) else None,
                    }
                    yield f"event: step_auto_proceeded\ndata: {json.dumps(auto_data)}\n\n"
                    continue
                else:
                    break
            
            # Get final state info
            final_state = mission.current_state or {}
            current_idx = final_state.get("current_agent_index", 0)
            workflow_agents = final_state.get("workflow_agents", [])
            current_agent = workflow_agents[current_idx] if current_idx < len(workflow_agents) else None
            
            # Resolve template_id for this step (if any)
            wf_config = final_state.get("workflow_config", [])
            step_template_id = None
            if wf_config and current_idx < len(wf_config):
                step_template_id = wf_config[current_idx].get("template_id")
            
            # Look up agent output — template steps use composite key
            agent_outputs = final_state.get("agent_outputs", {})
            if step_template_id and current_agent:
                agent_output = agent_outputs.get(f"{current_agent}:{step_template_id}") or agent_outputs.get(current_agent)
            elif current_agent:
                agent_output = agent_outputs.get(current_agent)
            else:
                agent_output = None
            
            # Determine step response
            step_data = {
                "mission_id": mission_id,
                "current_agent": current_agent,
                "current_agent_index": current_idx,
                "total_agents": len(workflow_agents),
                "status": mission.status,
                "agent_output": agent_output,
                "template_id": step_template_id,
                "can_continue": current_idx < len(workflow_agents) - 1,
                "can_skip": current_idx < len(workflow_agents),
                "is_final": mission.status == "COMPLETED",
                "workflow_agents": workflow_agents,
                "workflow_config": wf_config,
                "skipped_agents": final_state.get("skipped_agents", []),
            }
            
            yield f"event: step_complete\ndata: {json.dumps(step_data)}\n\n"
            
        except Exception as e:
            logger.exception("[MissionStep] Error in mission %s", mission_id)
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
        
        finally:
            # Always release the lock
            _mission_locks.pop(mission_id, None)
            logger.info("[MissionStep] released_lock rid=%s mission_id=%s", rid, mission_id)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/missions/{mission_id}/continue")
async def continue_step(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Continue to the next agent in the workflow.
    
    Called when merchant approves the current agent's output.
    Advances current_agent_index and sets status to PENDING for next run-step call.
    """
    rid = _rid(request)
    from src.ecommerce.db.models import Mission
    from src.ecommerce.orchestrator import MissionControl, MissionState
    from src.ecommerce.services import ServiceRegistry
    
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    if mission.status != "AWAITING_APPROVAL":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot continue - mission is {mission.status}"
        )
    
    # Load state and advance to next step
    state_dict = mission.current_state or {}
    state = MissionState.from_dict(state_dict, db=db)
    state.mission_id = mission_id
    
    # Create services with db/shop for usage tracking
    services = ServiceRegistry.create_default(db=db, shop_domain=shop)
    requested_agents = state_dict.get("requested_agents")
    wf_config = state_dict.get("workflow_config")
    
    mission_control = MissionControl(
        plan_tier=mission.plan_tier or "Basic",
        shop_id=shop,
        services=services,
        requested_agents=requested_agents,
        mission_id=mission_id,  # Pass DB mission_id for consistent logging
        workflow_config=wf_config,
    )
    
    state = await mission_control.advance_to_next_step(state)
    
    # Update mission record
    mission.current_state = state.to_dict()
    mission.status = state.status
    mission.logs = state.logs
    
    if state.status == "COMPLETED":
        from datetime import datetime, timezone
        mission.completed_at = datetime.now(timezone.utc)
        
        # === Save to Shopify on completion ===
        from src.ecommerce.db.transactions import get_shop_access_token
        from src.ecommerce.services.shopify_service import (
            save_product_content_with_locale,
            save_product_metafields,
            create_article,
            get_default_blog_id,
            get_product_body,
            update_product_body,
            faq_json_to_html,
            hero_json_to_html,
            inject_section,
            create_collection,
        )
        import json
        
        access_token = get_shop_access_token(db, shop)
        product_id = state.product_id
        
        # ── Classify every agent_output by its template type ──────────────
        # Template-specific outputs need special save semantics:
        #   product/description  → overwrite product body
        #   product/faq          → append FAQ HTML to product body
        #   product/landing-hero → prepend/overwrite hero HTML in product body
        #   product/blog-post    → create a new Shopify blog article
        #   product/collection   → create a new Shopify collection
        #   marketing/*          → saved as metafields only, NEVER as product body
        #   (no template)        → base RewriterAgent → same as product/description
        TEMPLATE_TEMPLATES = {
            "product/faq", "product/landing-hero", "product/blog-post", "product/collection",
            "marketing/email-launch", "marketing/email-welcome", "marketing/email-abandoned",
            "marketing/ad-facebook", "marketing/ad-google",
        }
        
        product_title = None
        product_desc = None
        blog_post_outputs = []
        faq_outputs = []
        hero_outputs = []
        collection_outputs = []
        marketing_outputs = []
        
        outputs = state.agent_outputs or {}
        logger.debug(
            "[MissionStep] classifying agent_outputs rid=%s keys=%s",
            rid, list(outputs.keys()),
        )
        
        def _is_template_json(text: str) -> str | None:
            """Sniff whether *text* is template-specific JSON.
            
            Returns the detected template_id or None.
            """
            try:
                obj = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return None
            if not isinstance(obj, dict):
                return None
            if "faqs" in obj:
                return "product/faq"
            if "headline" in obj and ("hero_description" in obj or "subheadline" in obj):
                return "product/landing-hero"
            if "body_html" in obj and "title" in obj:
                return "product/blog-post"
            return None
        
        for key, out in outputs.items():
            tmpl = out.get("template_id") if isinstance(out, dict) else None
            if tmpl == "product/blog-post":
                blog_post_outputs.append(out)
            elif tmpl == "product/faq":
                faq_outputs.append(out)
            elif tmpl == "product/landing-hero":
                hero_outputs.append(out)
            elif tmpl == "product/collection":
                collection_outputs.append(out)
            elif tmpl and tmpl.startswith("marketing/"):
                marketing_outputs.append(out)
            elif tmpl not in TEMPLATE_TEMPLATES:
                # product/description template step OR base RewriterAgent output
                if isinstance(out, dict):
                    dc = out.get("draft_content")
                    if dc:
                        # Guard: if draft_content is template-specific JSON
                        # (FAQ / Hero / Blog), reclassify it instead of
                        # treating it as a product description.
                        sniffed = _is_template_json(dc)
                        if sniffed == "product/faq":
                            logger.warning(
                                "[MissionStep] reclassified draft_content as FAQ rid=%s key=%s",
                                rid, key,
                            )
                            faq_outputs.append({**out, "template_id": "product/faq"})
                        elif sniffed == "product/landing-hero":
                            logger.warning(
                                "[MissionStep] reclassified draft_content as Hero rid=%s key=%s",
                                rid, key,
                            )
                            hero_outputs.append({**out, "template_id": "product/landing-hero"})
                        elif sniffed == "product/blog-post":
                            logger.warning(
                                "[MissionStep] reclassified draft_content as BlogPost rid=%s key=%s",
                                rid, key,
                            )
                            blog_post_outputs.append({**out, "template_id": "product/blog-post"})
                        else:
                            product_desc = dc
                    if out.get("draft_title"):
                        product_title = out["draft_title"]
        
        # Fallback: use state.draft_* only when there are NO template steps
        # that could have overwritten them.
        has_template_steps = bool(blog_post_outputs or faq_outputs or hero_outputs or collection_outputs)
        if not product_title and not has_template_steps:
            product_title = state.draft_title
        if not product_desc and not has_template_steps:
            # Final guard: only use state.draft_content if it is NOT
            # template-specific JSON (FAQ/Hero/Blog).
            fallback_desc = state.draft_content
            if fallback_desc and _is_template_json(fallback_desc):
                logger.warning(
                    "[MissionStep] fallback draft_content is template JSON, skipping rid=%s sniffed=%s",
                    rid, _is_template_json(fallback_desc),
                )
                # Reclassify the fallback content
                sniffed = _is_template_json(fallback_desc)
                reclassified = {"draft_content": fallback_desc, "template_id": sniffed}
                if sniffed == "product/faq":
                    faq_outputs.append(reclassified)
                elif sniffed == "product/landing-hero":
                    hero_outputs.append(reclassified)
                elif sniffed == "product/blog-post":
                    blog_post_outputs.append(reclassified)
            else:
                product_desc = fallback_desc
        
        raw_input = state.raw_input or {}
        product_title = product_title or raw_input.get("product_name", "")
        
        # 1️⃣ Save product title and description
        if access_token and product_id and product_title and product_desc:
            try:
                primary_locale = raw_input.get("primary_locale", "en")
                target_locale = state.target_locale or "en"
                
                await save_product_content_with_locale(
                    shop_domain=shop,
                    access_token=access_token,
                    product_id=product_id,
                    title=product_title,
                    description=product_desc,
                    target_locale=target_locale,
                    shop_primary_locale=primary_locale,
                )
                logger.info(
                    "[MissionStep] saved_to_shopify rid=%s shop=%s product_id=%s",
                    rid, shop, product_id
                )
                try:
                    from src.ecommerce.db.transactions import record_successful_rewrite, record_feature_usage, log_usage_event
                    record_successful_rewrite(db, shop, amount=1)
                    record_feature_usage(db, shop, "rewriter", 1)
                    log_usage_event(
                        db, shop_domain=shop, plan_name=mission.plan_tier or "Basic",
                        event_type="mission_rewrite", feature="rewriter",
                        product_id=product_id, mission_id=mission.id,
                    )
                except Exception:
                    logger.debug("[MissionStep] rewriter credit tracking failed", exc_info=True)
            except Exception as e:
                logger.error(
                    "[MissionStep] shopify_save_failed rid=%s shop=%s err=%s",
                    rid, shop, str(e)
                )
        
        # 2️⃣ Inject FAQ / Hero sections into product description HTML
        if access_token and product_id and (faq_outputs or hero_outputs):
            try:
                # Fetch the current body (may have just been updated above)
                current_body = await get_product_body(shop, access_token, product_id) or ""
                body_changed = False
                
                # Hero: overwrite (keep only 1), prepend at top
                for hero_out in hero_outputs:
                    if hero_out.get("is_published"):
                        continue
                    hero_html = hero_json_to_html(hero_out.get("draft_content", ""))
                    if hero_html:
                        current_body = inject_section(
                            current_body, hero_html,
                            "<!-- cba-hero-start -->", "<!-- cba-hero-end -->",
                            position="prepend",
                        )
                        body_changed = True
                        logger.info(
                            "[MissionStep] hero_injected rid=%s shop=%s product_id=%s",
                            rid, shop, product_id,
                        )
                
                # FAQ: append at bottom (replace existing if markers present)
                for faq_out in faq_outputs:
                    if faq_out.get("is_published"):
                        continue
                    faq_html = faq_json_to_html(faq_out.get("draft_content", ""))
                    if faq_html:
                        current_body = inject_section(
                            current_body, faq_html,
                            "<!-- cba-faq-start -->", "<!-- cba-faq-end -->",
                            position="append",
                        )
                        body_changed = True
                        logger.info(
                            "[MissionStep] faq_injected rid=%s shop=%s product_id=%s",
                            rid, shop, product_id,
                        )
                
                if body_changed:
                    await update_product_body(shop, access_token, product_id, current_body)
            except Exception as e:
                logger.error(
                    "[MissionStep] section_inject_failed rid=%s shop=%s err=%s",
                    rid, shop, str(e),
                )
        
        # 2.5️⃣ Inject visual assets (refined image + ad) into product description + media gallery
        visual_assets = state.visual_assets or {}
        refined_url = visual_assets.get("refined_url")
        ad_url = visual_assets.get("ad_url")
        if access_token and product_id and (refined_url or ad_url):
            product_name = (state.raw_input or {}).get("product_name", "product")

            # Add images to product media gallery
            from src.ecommerce.services.shopify_service import add_product_image
            product_gid = product_id if product_id.startswith("gid://") else f"gid://shopify/Product/{product_id}"
            for url, label in [(refined_url, "AI-refined product image"), (ad_url, "marketing ad")]:
                if url:
                    try:
                        await add_product_image(
                            shop_domain=shop,
                            access_token=access_token,
                            product_id=product_gid,
                            image_url=url,
                            alt_text=f"{product_name} - {label}",
                        )
                    except Exception as e:
                        logger.warning("[MissionStep] add_product_image failed url=%s err=%s", url, e)

        
        # 3️⃣ Create blog articles for any product/blog-post steps
        if access_token and blog_post_outputs:
            try:
                blog_id = raw_input.get("blog_id", "")
                if not blog_id:
                    blog_id = await get_default_blog_id(shop, access_token)
                if blog_id:
                    for bp_out in blog_post_outputs:
                        # Skip if autonomous publish already created this article
                        if bp_out.get("is_published"):
                            logger.info(
                                "[MissionStep] blog_article_already_published rid=%s shop=%s (autonomous)",
                                rid, shop,
                            )
                            continue
                        bp_title = bp_out.get("draft_title") or "Untitled Post"
                        bp_body = bp_out.get("draft_content") or ""
                        try:
                            parsed = json.loads(bp_body)
                            if isinstance(parsed, dict):
                                bp_body = parsed.get("body_html", parsed.get("content", bp_body))
                                bp_title = parsed.get("title", bp_title)
                        except (json.JSONDecodeError, TypeError):
                            pass
                        await create_article(
                            shop_domain=shop,
                            access_token=access_token,
                            blog_id=blog_id,
                            title=bp_title,
                            body_html=bp_body,
                        )
                        logger.info(
                            "[MissionStep] blog_article_created rid=%s shop=%s blog_id=%s",
                            rid, shop, blog_id
                        )
                else:
                    logger.warning(
                        "[MissionStep] blog_post_skipped rid=%s shop=%s reason=no_blog_found",
                        rid, shop,
                    )
            except Exception as e:
                logger.error(
                    "[MissionStep] blog_article_failed rid=%s shop=%s err=%s",
                    rid, shop, str(e)
                )
        
        # 3.5️⃣ Create collections for any product/collection steps
        if access_token and collection_outputs:
            for coll_out in collection_outputs:
                if coll_out.get("is_published"):
                    logger.info(
                        "[MissionStep] collection_already_published rid=%s shop=%s (autonomous)",
                        rid, shop,
                    )
                    continue
                coll_name = raw_input.get("collection_name") or "Untitled Collection"
                coll_desc = coll_out.get("draft_content") or ""
                try:
                    parsed = json.loads(coll_desc)
                    if isinstance(parsed, dict):
                        coll_desc = parsed.get(
                            "description_html",
                            parsed.get("description", parsed.get("content", coll_desc)),
                        )
                except (json.JSONDecodeError, TypeError):
                    pass
                coll_product_ids = raw_input.get("product_ids") or []
                try:
                    await create_collection(
                        shop_domain=shop,
                        access_token=access_token,
                        title=coll_name,
                        description_html=coll_desc,
                        product_ids=coll_product_ids,
                    )
                    logger.info(
                        "[MissionStep] collection_created rid=%s shop=%s name=%s",
                        rid, shop, coll_name,
                    )
                except Exception as e:
                    logger.error(
                        "[MissionStep] collection_create_failed rid=%s shop=%s err=%s",
                        rid, shop, str(e),
                    )
        
        # 4️⃣ Save agent data to metafields
        if access_token and product_id:
            metafields_to_save = []
            
            # Social hooks
            if state.social_hooks:
                hooks_data = []
                for hook in state.social_hooks:
                    if hasattr(hook, 'model_dump'):
                        hooks_data.append(hook.model_dump())
                    elif hasattr(hook, 'dict'):
                        hooks_data.append(hook.dict())
                    elif isinstance(hook, dict):
                        hooks_data.append(hook)
                    else:
                        hooks_data.append(str(hook))
                
                metafields_to_save.append({
                    "namespace": "crossborder_agent",
                    "key": "social_hooks",
                    "value": json.dumps(hooks_data),
                    "type": "json",
                })
            
            # Pricing analysis
            if state.pricing_analysis:
                metafields_to_save.append({
                    "namespace": "crossborder_agent",
                    "key": "pricing_analysis",
                    "value": json.dumps(state.pricing_analysis),
                    "type": "json",
                })
            
            # SEO data
            seo_data = {
                "seo_title": state.seo_title,
                "seo_description": state.seo_description,
                "seo_alt_text": state.seo_alt_text,
                "ctr_check": state.ctr_check,
            }
            if any(seo_data.values()):
                metafields_to_save.append({
                    "namespace": "crossborder_agent",
                    "key": "seo_data",
                    "value": json.dumps(seo_data),
                    "type": "json",
                })
            
            # Marketing outputs (emails, ads) — save as metafield JSON
            if marketing_outputs:
                mktg_data = []
                for m_out in marketing_outputs:
                    mktg_data.append({
                        "template_id": m_out.get("template_id", ""),
                        "content": m_out.get("draft_content", ""),
                        "title": m_out.get("draft_title", ""),
                    })
                metafields_to_save.append({
                    "namespace": "crossborder_agent",
                    "key": "marketing_content",
                    "value": json.dumps(mktg_data),
                    "type": "json",
                })
            
            if metafields_to_save:
                try:
                    await save_product_metafields(
                        shop_domain=shop,
                        access_token=access_token,
                        product_id=product_id,
                        metafields=metafields_to_save,
                    )
                    logger.info(
                        "[MissionStep] metafields_saved rid=%s shop=%s count=%d",
                        rid, shop, len(metafields_to_save)
                    )
                except Exception as e:
                    logger.warning(
                        "[MissionStep] metafields_save_failed rid=%s shop=%s err=%s",
                        rid, shop, str(e)
                    )
        # === End Shopify save ===
    
    db.add(mission)
    db.commit()
    
    logger.info(
        "[MissionStep] continue rid=%s shop=%s mission_id=%s new_index=%d status=%s",
        rid, shop, mission_id, state.current_agent_index, state.status,
    )
    
    workflow_agents = state.workflow_agents
    current_idx = state.current_agent_index
    next_agent = workflow_agents[current_idx] if current_idx < len(workflow_agents) else None
    
    return {
        "status": "success",
        "mission_id": mission_id,
        "current_agent_index": current_idx,
        "next_agent": next_agent,
        "is_complete": state.status == "COMPLETED",
        "mission_status": state.status,
    }


@router.post("/api/missions/{mission_id}/approve")
async def approve_step(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Approve the current agent's output (alias for /continue).
    
    This is the Mission Architect-friendly name for the continue action.
    Functionally identical to POST /api/missions/{mission_id}/continue.
    """
    return await continue_step(mission_id=mission_id, request=request, db=db, shop=shop)


@router.post("/api/missions/{mission_id}/regenerate")
async def regenerate_step(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Regenerate the current agent's output with optional feedback.
    
    Called when merchant wants to try again with the current agent.
    Sets regeneration_feedback in state and status to PENDING for next run-step call.
    """
    rid = _rid(request)
    
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    try:
        regen_req = RegenerateRequest(**body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    
    from src.ecommerce.db.models import Mission
    from src.ecommerce.orchestrator import MissionControl, MissionState
    from src.ecommerce.services import ServiceRegistry
    
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    if mission.status != "AWAITING_APPROVAL":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot regenerate - mission is {mission.status}"
        )
    
    # Load state and prepare for regeneration
    state_dict = mission.current_state or {}
    state = MissionState.from_dict(state_dict, db=db)
    state.mission_id = mission_id
    
    # Create services with db/shop for usage tracking
    services = ServiceRegistry.create_default(db=db, shop_domain=shop)
    requested_agents = state_dict.get("requested_agents")
    wf_config = state_dict.get("workflow_config")
    
    mission_control = MissionControl(
        plan_tier=mission.plan_tier or "Basic",
        shop_id=shop,
        services=services,
        requested_agents=requested_agents,
        mission_id=mission_id,  # Pass DB mission_id for consistent logging
        workflow_config=wf_config,
    )
    
    state = mission_control.prepare_regeneration(state, feedback=regen_req.feedback)
    
    # Update mission record
    mission.current_state = state.to_dict()
    mission.status = state.status
    mission.logs = state.logs
    db.add(mission)
    db.commit()
    
    logger.info(
        "[MissionStep] regenerate rid=%s shop=%s mission_id=%s agent_index=%d has_feedback=%s",
        rid, shop, mission_id, state.current_agent_index, bool(regen_req.feedback),
    )
    
    workflow_agents = state.workflow_agents
    current_idx = state.current_agent_index
    current_agent = workflow_agents[current_idx] if current_idx < len(workflow_agents) else None
    
    return {
        "status": "success",
        "mission_id": mission_id,
        "current_agent": current_agent,
        "current_agent_index": current_idx,
        "mission_status": state.status,
        "feedback_applied": bool(regen_req.feedback),
    }


@router.post("/api/missions/{mission_id}/skip")
async def skip_step(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Skip the current agent in the workflow.
    
    Called when merchant doesn't want to run the current agent.
    Records skipped agent and advances to next step.
    """
    rid = _rid(request)
    from src.ecommerce.db.models import Mission
    from src.ecommerce.orchestrator import MissionControl, MissionState
    from src.ecommerce.services import ServiceRegistry
    
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    
    if mission.status not in ("AWAITING_APPROVAL", "PENDING"):
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot skip - mission is {mission.status}"
        )
    
    # Load state and skip current step
    state_dict = mission.current_state or {}
    state = MissionState.from_dict(state_dict, db=db)
    state.mission_id = mission_id
    
    # Create services with db/shop for usage tracking
    services = ServiceRegistry.create_default(db=db, shop_domain=shop)
    requested_agents = state_dict.get("requested_agents")
    wf_config = state_dict.get("workflow_config")
    
    mission_control = MissionControl(
        plan_tier=mission.plan_tier or "Basic",
        shop_id=shop,
        services=services,
        requested_agents=requested_agents,
        mission_id=mission_id,  # Pass DB mission_id for consistent logging
        workflow_config=wf_config,
    )
    
    # Record which agent was skipped
    workflow_agents = state.workflow_agents or [a.__name__ for a in mission_control.workflow]
    current_idx = state.current_agent_index
    skipped_agent = workflow_agents[current_idx] if current_idx < len(workflow_agents) else None
    
    state = mission_control.skip_current_step(state)
    
    # Update mission record
    mission.current_state = state.to_dict()
    mission.status = state.status
    mission.logs = state.logs
    
    if state.status == "COMPLETED":
        from datetime import datetime, timezone
        mission.completed_at = datetime.now(timezone.utc)
        
        # === Save to Shopify on completion (if we have content) ===
        from src.ecommerce.db.transactions import get_shop_access_token
        from src.ecommerce.services.shopify_service import (
            save_product_content_with_locale,
            save_product_metafields,
            create_article,
            get_default_blog_id,
            get_product_body,
            update_product_body,
            faq_json_to_html,
            hero_json_to_html,
            inject_section,
            create_collection,
        )
        import json
        
        access_token = get_shop_access_token(db, shop)
        product_id = state.product_id
        
        # ── Classify agent_outputs by template type ───────────────────────
        TEMPLATE_TEMPLATES = {
            "product/faq", "product/landing-hero", "product/blog-post", "product/collection",
            "marketing/email-launch", "marketing/email-welcome", "marketing/email-abandoned",
            "marketing/ad-facebook", "marketing/ad-google",
        }
        
        product_title = None
        product_desc = None
        blog_post_outputs = []
        faq_outputs = []
        hero_outputs = []
        collection_outputs = []
        marketing_outputs = []
        
        outputs = state.agent_outputs or {}
        logger.debug(
            "[MissionStep] classifying agent_outputs (skip) rid=%s keys=%s",
            rid, list(outputs.keys()),
        )
        
        def _is_template_json(text: str) -> str | None:
            """Sniff whether *text* is template-specific JSON."""
            try:
                obj = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return None
            if not isinstance(obj, dict):
                return None
            if "faqs" in obj:
                return "product/faq"
            if "headline" in obj and ("hero_description" in obj or "subheadline" in obj):
                return "product/landing-hero"
            if "body_html" in obj and "title" in obj:
                return "product/blog-post"
            return None
        
        for key, out in outputs.items():
            tmpl = out.get("template_id") if isinstance(out, dict) else None
            if tmpl == "product/blog-post":
                blog_post_outputs.append(out)
            elif tmpl == "product/faq":
                faq_outputs.append(out)
            elif tmpl == "product/landing-hero":
                hero_outputs.append(out)
            elif tmpl == "product/collection":
                collection_outputs.append(out)
            elif tmpl and tmpl.startswith("marketing/"):
                marketing_outputs.append(out)
            elif tmpl not in TEMPLATE_TEMPLATES:
                if isinstance(out, dict):
                    dc = out.get("draft_content")
                    if dc:
                        sniffed = _is_template_json(dc)
                        if sniffed == "product/faq":
                            logger.warning(
                                "[MissionStep] reclassified draft_content as FAQ (skip) rid=%s key=%s",
                                rid, key,
                            )
                            faq_outputs.append({**out, "template_id": "product/faq"})
                        elif sniffed == "product/landing-hero":
                            logger.warning(
                                "[MissionStep] reclassified draft_content as Hero (skip) rid=%s key=%s",
                                rid, key,
                            )
                            hero_outputs.append({**out, "template_id": "product/landing-hero"})
                        elif sniffed == "product/blog-post":
                            logger.warning(
                                "[MissionStep] reclassified draft_content as BlogPost (skip) rid=%s key=%s",
                                rid, key,
                            )
                            blog_post_outputs.append({**out, "template_id": "product/blog-post"})
                        else:
                            product_desc = dc
                    if out.get("draft_title"):
                        product_title = out["draft_title"]
        
        has_template_steps = bool(blog_post_outputs or faq_outputs or hero_outputs or collection_outputs)
        if not product_title and not has_template_steps:
            product_title = state.draft_title
        if not product_desc and not has_template_steps:
            fallback_desc = state.draft_content
            if fallback_desc and _is_template_json(fallback_desc):
                logger.warning(
                    "[MissionStep] fallback draft_content is template JSON (skip), skipping rid=%s sniffed=%s",
                    rid, _is_template_json(fallback_desc),
                )
                sniffed = _is_template_json(fallback_desc)
                reclassified = {"draft_content": fallback_desc, "template_id": sniffed}
                if sniffed == "product/faq":
                    faq_outputs.append(reclassified)
                elif sniffed == "product/landing-hero":
                    hero_outputs.append(reclassified)
                elif sniffed == "product/blog-post":
                    blog_post_outputs.append(reclassified)
            else:
                product_desc = fallback_desc
        
        raw_input = state.raw_input or {}
        product_title = product_title or raw_input.get("product_name", "")
        
        # 1️⃣ Save product title and description
        if access_token and product_id and product_title and product_desc:
            try:
                primary_locale = raw_input.get("primary_locale", "en")
                target_locale = state.target_locale or "en"
                
                await save_product_content_with_locale(
                    shop_domain=shop,
                    access_token=access_token,
                    product_id=product_id,
                    title=product_title,
                    description=product_desc,
                    target_locale=target_locale,
                    shop_primary_locale=primary_locale,
                )
                logger.info(
                    "[MissionStep] saved_to_shopify rid=%s shop=%s product_id=%s (via skip)",
                    rid, shop, product_id
                )
                try:
                    from src.ecommerce.db.transactions import record_successful_rewrite, record_feature_usage, log_usage_event
                    record_successful_rewrite(db, shop, amount=1)
                    record_feature_usage(db, shop, "rewriter", 1)
                    log_usage_event(
                        db, shop_domain=shop, plan_name=mission.plan_tier or "Basic",
                        event_type="mission_rewrite", feature="rewriter",
                        product_id=product_id, mission_id=mission.id,
                    )
                except Exception:
                    logger.debug("[MissionStep] rewriter credit tracking failed (via skip)", exc_info=True)
            except Exception as e:
                logger.error(
                    "[MissionStep] shopify_save_failed rid=%s shop=%s err=%s (via skip)",
                    rid, shop, str(e)
                )
        
        # 2️⃣ Inject FAQ / Hero sections into product description HTML
        if access_token and product_id and (faq_outputs or hero_outputs):
            try:
                current_body = await get_product_body(shop, access_token, product_id) or ""
                body_changed = False
                
                for hero_out in hero_outputs:
                    if hero_out.get("is_published"):
                        continue
                    hero_html = hero_json_to_html(hero_out.get("draft_content", ""))
                    if hero_html:
                        current_body = inject_section(
                            current_body, hero_html,
                            "<!-- cba-hero-start -->", "<!-- cba-hero-end -->",
                            position="prepend",
                        )
                        body_changed = True
                
                for faq_out in faq_outputs:
                    if faq_out.get("is_published"):
                        continue
                    faq_html = faq_json_to_html(faq_out.get("draft_content", ""))
                    if faq_html:
                        current_body = inject_section(
                            current_body, faq_html,
                            "<!-- cba-faq-start -->", "<!-- cba-faq-end -->",
                            position="append",
                        )
                        body_changed = True
                
                if body_changed:
                    await update_product_body(shop, access_token, product_id, current_body)
                    logger.info(
                        "[MissionStep] sections_injected rid=%s shop=%s product_id=%s (via skip)",
                        rid, shop, product_id,
                    )
            except Exception as e:
                logger.error(
                    "[MissionStep] section_inject_failed rid=%s shop=%s err=%s (via skip)",
                    rid, shop, str(e),
                )
        
        
        # 3️⃣ Create blog articles for any product/blog-post steps
        if access_token and blog_post_outputs:
            try:
                blog_id = raw_input.get("blog_id", "")
                if not blog_id:
                    blog_id = await get_default_blog_id(shop, access_token)
                if blog_id:
                    for bp_out in blog_post_outputs:
                        # Skip if autonomous publish already created this article
                        if bp_out.get("is_published"):
                            logger.info(
                                "[MissionStep] blog_article_already_published rid=%s shop=%s (autonomous, via skip)",
                                rid, shop,
                            )
                            continue
                        bp_title = bp_out.get("draft_title") or "Untitled Post"
                        bp_body = bp_out.get("draft_content") or ""
                        try:
                            parsed = json.loads(bp_body)
                            if isinstance(parsed, dict):
                                bp_body = parsed.get("body_html", parsed.get("content", bp_body))
                                bp_title = parsed.get("title", bp_title)
                        except (json.JSONDecodeError, TypeError):
                            pass
                        await create_article(
                            shop_domain=shop,
                            access_token=access_token,
                            blog_id=blog_id,
                            title=bp_title,
                            body_html=bp_body,
                        )
                        logger.info(
                            "[MissionStep] blog_article_created rid=%s shop=%s blog_id=%s (via skip)",
                            rid, shop, blog_id
                        )
                else:
                    logger.warning(
                        "[MissionStep] blog_post_skipped rid=%s shop=%s reason=no_blog_found (via skip)",
                        rid, shop,
                    )
            except Exception as e:
                logger.error(
                    "[MissionStep] blog_article_failed rid=%s shop=%s err=%s (via skip)",
                    rid, shop, str(e)
                )
        
        # 3.5️⃣ Create collections for any product/collection steps
        if access_token and collection_outputs:
            for coll_out in collection_outputs:
                if coll_out.get("is_published"):
                    logger.info(
                        "[MissionStep] collection_already_published rid=%s shop=%s (autonomous, via skip)",
                        rid, shop,
                    )
                    continue
                coll_name = raw_input.get("collection_name") or "Untitled Collection"
                coll_desc = coll_out.get("draft_content") or ""
                try:
                    parsed = json.loads(coll_desc)
                    if isinstance(parsed, dict):
                        coll_desc = parsed.get(
                            "description_html",
                            parsed.get("description", parsed.get("content", coll_desc)),
                        )
                except (json.JSONDecodeError, TypeError):
                    pass
                coll_product_ids = raw_input.get("product_ids") or []
                try:
                    await create_collection(
                        shop_domain=shop,
                        access_token=access_token,
                        title=coll_name,
                        description_html=coll_desc,
                        product_ids=coll_product_ids,
                    )
                    logger.info(
                        "[MissionStep] collection_created rid=%s shop=%s name=%s (via skip)",
                        rid, shop, coll_name,
                    )
                except Exception as e:
                    logger.error(
                        "[MissionStep] collection_create_failed rid=%s shop=%s err=%s (via skip)",
                        rid, shop, str(e),
                )
        
        # Save metafields if we have any data
        if access_token and product_id:
            metafields_to_save = []
            
            if state.social_hooks:
                hooks_data = []
                for hook in state.social_hooks:
                    if hasattr(hook, 'model_dump'):
                        hooks_data.append(hook.model_dump())
                    elif hasattr(hook, 'dict'):
                        hooks_data.append(hook.dict())
                    elif isinstance(hook, dict):
                        hooks_data.append(hook)
                    else:
                        hooks_data.append(str(hook))
                
                metafields_to_save.append({
                    "namespace": "crossborder_agent",
                    "key": "social_hooks",
                    "value": json.dumps(hooks_data),
                    "type": "json",
                })
            
            if state.pricing_analysis:
                metafields_to_save.append({
                    "namespace": "crossborder_agent",
                    "key": "pricing_analysis",
                    "value": json.dumps(state.pricing_analysis),
                    "type": "json",
                })
            
            seo_data = {
                "seo_title": state.seo_title,
                "seo_description": state.seo_description,
                "seo_alt_text": state.seo_alt_text,
                "ctr_check": state.ctr_check,
            }
            if any(seo_data.values()):
                metafields_to_save.append({
                    "namespace": "crossborder_agent",
                    "key": "seo_data",
                    "value": json.dumps(seo_data),
                    "type": "json",
                })
            
            # Marketing outputs (emails, ads)
            if marketing_outputs:
                mktg_data = []
                for m_out in marketing_outputs:
                    mktg_data.append({
                        "template_id": m_out.get("template_id", ""),
                        "content": m_out.get("draft_content", ""),
                        "title": m_out.get("draft_title", ""),
                    })
                metafields_to_save.append({
                    "namespace": "crossborder_agent",
                    "key": "marketing_content",
                    "value": json.dumps(mktg_data),
                    "type": "json",
                })
            
            if metafields_to_save:
                try:
                    await save_product_metafields(
                        shop_domain=shop,
                        access_token=access_token,
                        product_id=product_id,
                        metafields=metafields_to_save,
                    )
                    logger.info(
                        "[MissionStep] metafields_saved rid=%s shop=%s count=%d (via skip)",
                        rid, shop, len(metafields_to_save)
                    )
                except Exception as e:
                    logger.warning(
                        "[MissionStep] metafields_save_failed rid=%s shop=%s err=%s (via skip)",
                        rid, shop, str(e)
                    )
        # === End Shopify save ===
    
    db.add(mission)
    db.commit()
    
    logger.info(
        "[MissionStep] skip rid=%s shop=%s mission_id=%s skipped=%s new_index=%d status=%s",
        rid, shop, mission_id, skipped_agent, state.current_agent_index, state.status,
    )
    
    next_agent = None
    if state.current_agent_index < len(workflow_agents):
        next_agent = workflow_agents[state.current_agent_index]
    
    return {
        "status": "success",
        "mission_id": mission_id,
        "skipped_agent": skipped_agent,
        "current_agent_index": state.current_agent_index,
        "next_agent": next_agent,
        "is_complete": state.status == "COMPLETED",
        "mission_status": state.status,
        "skipped_agents": state.skipped_agents,
    }


# =============================================================================
# Cancel Mission
# =============================================================================

@router.post("/api/missions/{mission_id}/cancel")
async def cancel_mission(
    mission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """Cancel a mission. Works for any non-completed status."""
    rid = _rid(request)
    from src.ecommerce.db.models import Mission

    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.shop_id == shop,
    ).first()

    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    if mission.status == "COMPLETED":
        raise HTTPException(status_code=400, detail="Cannot cancel a completed mission")

    logger.info(
        "[MissionCancel] rid=%s shop=%s mission_id=%s prev_status=%s",
        rid, shop, mission_id, mission.status,
    )

    mission.status = "CANCELLED"
    state_dict = mission.current_state or {}
    state_dict["status"] = "CANCELLED"
    mission.current_state = state_dict
    mission.logs = (mission.logs or []) + [f"Mission cancelled by merchant (was {mission.status})"]
    db.add(mission)
    db.commit()

    _mission_locks.pop(mission_id, None)

    return {"status": "cancelled", "mission_id": mission_id}


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
    from src.ecommerce.db.models import AgentCorrection
    
    correction_id = uuid.uuid4().hex
    
    # Generate embedding for the correction (for future similarity search)
    embedding = None
    try:
        from src.agentic_core.rag.embedding.embedding import embed_texts
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
    from src.ecommerce.db.models import AgentCorrection
    
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


# =============================================================================
# Bulk Upload Mission Endpoints (Pro Only)
# =============================================================================

from fastapi import UploadFile, File, Form


@router.post("/api/missions/bulk")
async def create_bulk_mission(
    request: Request,
    file: UploadFile = File(...),
    payload: str = Form(...),
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Create a bulk upload mission (Pro only).

    Accepts multipart/form-data with a CSV or ZIP file and JSON preferences.
    Creates a parent mission and up to 10 child missions, then launches
    async background processing.
    """
    import uuid
    import shutil
    from datetime import datetime, timezone
    from src.ecommerce.db.models import Mission, Shop as ShopModel
    from src.ecommerce.services.bulk_upload_parser import parse_upload

    rid = _rid(request)

    # Parse JSON payload
    try:
        bulk_req = BulkMissionRequest(**json.loads(payload))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid payload JSON: {e}")

    # Auth + plan gating
    auth_context = validate_shop_and_quota(db, shop, enforce_limit=False)
    validate_feature_access(auth_context, "bulk_upload")

    plan = auth_context["plan"]
    plan_tier = getattr(plan, "name", "Pro")
    shop_obj: ShopModel = auth_context["shop"]
    ent = get_entitlements(plan_tier)

    # Pre-flight image credit check for full_launch
    if bulk_req.mission_type == "full_launch":
        image_limit = int(ent.get("image_generation_limit", 0))
        image_used = int(getattr(shop_obj, "monthly_image_generations_used", 0) or 0)
        # We don't know N yet — read file first, then check
    else:
        image_limit = 0
        image_used = 0

    # Read and parse file
    file_bytes = await file.read()
    filename = file.filename or "upload.csv"
    items, temp_dir = await parse_upload(file_bytes, filename, bulk_req.mission_type)
    n_products = len(items)

    # Image credit check (now that we know N)
    if bulk_req.mission_type == "full_launch":
        remaining = max(0, image_limit - image_used)
        if n_products > remaining:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(
                status_code=422,
                detail=f"Batch requires {n_products} image credits but you have {remaining} remaining this month.",
            )

    # Upload images to R2 for full_launch
    image_urls: dict[str, str] = {}
    if bulk_req.mission_type == "full_launch" and temp_dir:
        from src.ecommerce.services.r2_storage_service import R2StorageService
        r2 = R2StorageService()
        for item in items:
            if item.image_path:
                with open(item.image_path, "rb") as f:
                    img_bytes = f.read()
                ext = os.path.splitext(item.image_ref or "img.png")[1].lstrip(".") or "png"
                key = f"bulk/{shop}/{uuid.uuid4().hex}/{item.image_ref or 'image.png'}"
                url = await r2.upload_asset(img_bytes, key, content_type=f"image/{ext}")
                image_urls[item.row_id] = url

    # Clean up temp dir
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Build workflow_config based on mission type
    if bulk_req.mission_type == "text_only":
        workflow_config = [
            {"agent_name": "RewriterAgent", "has_gate": False},
            {"agent_name": "SEOAgent", "has_gate": False},
        ]
        mission_label = f"Bulk Text Upload ({n_products} products)"
    else:
        workflow_config = [
            {"agent_name": "RewriterAgent", "has_gate": False},
            {"agent_name": "ImageRefinementAgent", "has_gate": False},
            {"agent_name": "SEOAgent", "has_gate": False},
        ]
        mission_label = f"Bulk Full Launch ({n_products} products)"

    workflow_agents = [step["agent_name"] for step in workflow_config]
    prefs = bulk_req.preferences

    # Create parent bulk mission
    parent_id = uuid.uuid4().hex
    parent_mission = Mission(
        id=parent_id,
        shop_id=shop,
        product_id="bulk",
        status="IN_PROGRESS",
        current_state={
            "is_bulk_parent": True,
            "mission_type": bulk_req.mission_type,
            "total": n_products,
            "completed": 0,
            "failed": 0,
            "image_credits_used": 0,
            "child_ids": [],
            "raw_input": {"mission_title": mission_label},
        },
        logs=[],
        plan_tier=plan_tier,
    )
    db.add(parent_mission)

    # Create child missions
    child_ids = []
    for item in items:
        child_id = uuid.uuid4().hex
        child_ids.append(child_id)

        raw_input = {
            "product_id": item.row_id,
            "title": item.product_name_ja,
            "product_name": item.product_name_ja,
            "description": item.description_ja,
            "japanese_description": item.description_ja,
            "category": item.category,
            "tone": prefs.tone_profile,
            "target_locale": item.target_market,
            "brand_soul_enabled": bool(auth_context.get("brand_soul_enabled", True)),
            "us_units_conversion": prefs.us_units_conversion,
            "image_url": image_urls.get(item.row_id),
            "brand_name": shop.split(".")[0].replace("-", " ").title(),
            "_bulk_mission": True,
            "_bulk_parent_id": parent_id,
            "mission_title": mission_label,
        }

        initial_state = {
            "product_id": item.row_id,
            "shop_id": shop,
            "plan_tier": plan_tier,
            "raw_input": raw_input,
            "target_locale": item.target_market,
            "status": "PENDING",
            "logs": [],
            "current_agent_index": 0,
            "skipped_agents": [],
            "agent_outputs": {},
            "workflow_agents": workflow_agents,
            "workflow_config": workflow_config,
            "autonomous": True,
        }

        child_mission = Mission(
            id=child_id,
            shop_id=shop,
            product_id=item.row_id,
            status="PENDING",
            current_state=initial_state,
            logs=[],
            plan_tier=plan_tier,
            bulk_mission_id=parent_id,
        )
        db.add(child_mission)

    # Update parent with child IDs
    parent_state = parent_mission.current_state.copy()
    parent_state["child_ids"] = child_ids
    parent_mission.current_state = parent_state

    # Increment mission counter
    mission_limit_type = ent.get("mission_limit_type", "monthly")
    if mission_limit_type == "lifetime":
        shop_obj.lifetime_missions_remaining = max(
            0, int(getattr(shop_obj, "lifetime_missions_remaining", 0) or 0) - n_products
        )
    else:
        shop_obj.monthly_missions_used = int(getattr(shop_obj, "monthly_missions_used", 0) or 0) + n_products
    db.add(shop_obj)

    db.commit()

    # Estimate processing time (~2 min per product for text_only, ~3 for full_launch)
    per_product_minutes = 3 if bulk_req.mission_type == "full_launch" else 2
    estimated_minutes = n_products * per_product_minutes

    logger.info(
        "[BulkMission] created rid=%s shop=%s parent=%s children=%d type=%s",
        rid, shop, parent_id, n_products, bulk_req.mission_type,
    )

    # Launch background task
    asyncio.create_task(
        _run_bulk_mission_background(
            parent_id=parent_id,
            child_ids=child_ids,
            shop_domain=shop,
            plan_tier=plan_tier,
            mission_type=bulk_req.mission_type,
        )
    )

    return {
        "bulk_mission_id": parent_id,
        "child_mission_ids": child_ids,
        "total": n_products,
        "estimated_minutes": estimated_minutes,
    }


async def _run_bulk_mission_background(
    parent_id: str,
    child_ids: list[str],
    shop_domain: str,
    plan_tier: str,
    mission_type: str,
) -> None:
    """
    Background task that processes each child mission sequentially,
    then creates the product in Shopify and updates statuses.
    """
    from src.ecommerce.orchestrator import MissionControl, MissionState
    from src.ecommerce.services import ServiceRegistry
    from src.ecommerce.db.transactions import get_shop_access_token
    from src.ecommerce.services.shopify_service import create_product_in_shopify
    from src.shared.db.database import SessionLocal

    db = SessionLocal()
    try:
        from src.ecommerce.db.models import Mission, Shop as ShopModel

        parent = db.query(Mission).filter(Mission.id == parent_id).first()
        if not parent:
            logger.error("[BulkBG] parent mission not found: %s", parent_id)
            return

        access_token = get_shop_access_token(db, shop_domain)
        completed = 0
        failed = 0
        image_credits_used = 0

        for child_id in child_ids:
            child = db.query(Mission).filter(Mission.id == child_id).first()
            if not child:
                failed += 1
                continue

            try:
                child.status = "IN_PROGRESS"
                db.add(child)
                db.commit()

                state_dict = child.current_state or {}
                state = MissionState.from_dict(state_dict, db=db)
                state.mission_id = child_id

                services = ServiceRegistry.create_default(db=db, shop_domain=shop_domain)
                wf_config = state_dict.get("workflow_config")

                mission_control = MissionControl(
                    plan_tier=plan_tier,
                    shop_id=shop_domain,
                    services=services,
                    mission_id=child_id,
                    workflow_config=wf_config,
                )

                last_state = None
                async for s in mission_control.execute(state):
                    last_state = s
                    child.current_state = s.to_dict()
                    child.status = s.status
                    child.logs = s.logs
                    db.add(child)
                    db.commit()

                if last_state and last_state.status != "ERROR":
                    # Read category from the original state dict first, then
                    # fall back to the agent's preserved raw_input.
                    raw = state_dict.get("raw_input") or {}
                    agent_raw = (last_state.raw_input if hasattr(last_state, "raw_input") else {}) or {}
                    category = raw.get("category") or agent_raw.get("category") or ""

                    product_data = {
                        "title": last_state.draft_title or raw.get("product_name", ""),
                        "description_html": last_state.draft_content or "",
                        "product_type": category,
                        "seo_title": last_state.seo_title or "",
                        "seo_description": last_state.seo_description or "",
                        "seo_alt_text": last_state.seo_alt_text or "",
                    }

                    logger.info(
                        "[BulkBG] product_data child=%s category=%r title=%r",
                        child_id, category, product_data["title"][:60],
                    )

                    # For full_launch, use refined image if available
                    visual_assets = last_state.visual_assets or {}
                    refined_url = visual_assets.get("refined_url")
                    if refined_url:
                        product_data["image_url"] = refined_url
                        image_credits_used += 1
                    elif state_dict.get("raw_input", {}).get("image_url"):
                        product_data["image_url"] = state_dict["raw_input"]["image_url"]

                    if access_token:
                        try:
                            product_gid = await create_product_in_shopify(
                                shop_domain=shop_domain,
                                access_token=access_token,
                                product_data=product_data,
                            )
                            logger.info(
                                "[BulkBG] product_created child=%s product_gid=%s",
                                child_id, product_gid,
                            )
                        except Exception as e:
                            logger.error(
                                "[BulkBG] product_create_failed child=%s err=%s",
                                child_id, str(e)[:200],
                            )

                    child.status = "COMPLETED"
                    from datetime import datetime, timezone as tz
                    child.completed_at = datetime.now(tz.utc)
                    completed += 1
                else:
                    child.status = "ERROR"
                    child.error_message = getattr(last_state, "error_message", None) or "Agent pipeline failed"
                    failed += 1

            except Exception as e:
                logger.exception("[BulkBG] child_failed child=%s err=%s", child_id, str(e)[:200])
                child.status = "ERROR"
                child.error_message = str(e)[:500]
                failed += 1

            db.add(child)
            db.commit()

            # Update parent progress
            parent_state = dict(parent.current_state or {})
            parent_state["completed"] = completed
            parent_state["failed"] = failed
            parent_state["image_credits_used"] = image_credits_used
            parent.current_state = parent_state
            db.add(parent)
            db.commit()

        # Finalize parent
        from datetime import datetime, timezone as tz
        parent.status = "COMPLETED"
        parent.completed_at = datetime.now(tz.utc)
        parent_state = dict(parent.current_state or {})
        parent_state["completed"] = completed
        parent_state["failed"] = failed
        parent_state["image_credits_used"] = image_credits_used
        parent.current_state = parent_state
        db.add(parent)
        db.commit()

        logger.info(
            "[BulkBG] done parent=%s completed=%d failed=%d images=%d",
            parent_id, completed, failed, image_credits_used,
        )

    except Exception as e:
        logger.exception("[BulkBG] fatal error parent=%s err=%s", parent_id, str(e)[:300])
        try:
            parent = db.query(Mission).filter(Mission.id == parent_id).first()
            if parent:
                parent.status = "ERROR"
                parent.error_message = str(e)[:500]
                db.add(parent)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/api/missions/bulk/{bulk_id}/status")
async def get_bulk_mission_status(
    bulk_id: str,
    request: Request,
    db: Session = Depends(get_db),
    shop: str = Depends(resolve_shop_domain),
):
    """
    Poll the status of a bulk upload mission.

    Returns aggregate progress counts and a shop products URL when complete.
    """
    from src.ecommerce.db.models import Mission

    mission = db.query(Mission).filter(
        Mission.id == bulk_id,
        Mission.shop_id == shop,
    ).first()

    if not mission:
        raise HTTPException(status_code=404, detail="Bulk mission not found")

    state = mission.current_state or {}
    if not state.get("is_bulk_parent"):
        raise HTTPException(status_code=404, detail="Not a bulk mission")

    total = state.get("total", 0)
    completed = state.get("completed", 0)
    failed = state.get("failed", 0)
    image_credits_used = state.get("image_credits_used", 0)
    mission_type = state.get("mission_type", "text_only")

    # Estimate remaining time
    remaining_products = total - completed - failed
    per_product = 3 if mission_type == "full_launch" else 2
    estimated_remaining_minutes = max(0, remaining_products * per_product)

    result = {
        "bulk_mission_id": bulk_id,
        "status": mission.status,
        "mission_type": mission_type,
        "total": total,
        "completed": completed,
        "failed": failed,
        "image_credits_used": image_credits_used,
        "estimated_remaining_minutes": estimated_remaining_minutes,
    }

    if mission.status == "COMPLETED":
        shop_base = shop.replace(".myshopify.com", "")
        result["shop_products_url"] = f"https://admin.shopify.com/store/{shop_base}/products"

    return result

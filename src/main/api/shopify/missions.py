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

from src.main.api.models import (
    MissionRequest, 
    CorrectionRequest,
    RegenerateRequest,
    StepResponse,
    MissionStatusResponse,
)
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
    from src.main.db.db_models import Mission
    
    rid = _rid(request)
    logger.info("[MissionList] rid=%s shop=%s limit=%d", rid, shop, limit)
    
    all_missions = db.query(Mission).filter(
        Mission.shop_id == shop
    ).order_by(Mission.created_at.desc()).limit(limit * 2).all()  # Fetch extra to account for filtering
    
    # Filter out ad-hoc missions (single-agent runs like SEO-only or Pricing-only)
    missions = [
        m for m in all_missions
        if not (m.current_state or {}).get("is_adhoc", False)
    ][:limit]  # Apply limit after filtering
    
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
    
    # Mission Architect workflow_config takes priority
    workflow_config = mission_req.workflow_config
    
    # Determine workflow agents based on workflow_config, ad-hoc selection, or tier
    from src.main.agents import MissionControl
    from src.main.services import ServiceRegistry
    
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
            "brand_soul_enabled": mission_req.brand_soul_enabled,
    }
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
    from src.main.db.db_models import Mission
    
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
    if mission.status == "IN_PROGRESS":
        logger.warning(
            "[MissionStream] resetting_stuck_mission rid=%s mission_id=%s from IN_PROGRESS to PENDING",
            rid, mission_id
        )
        mission.status = "PENDING"
        db.add(mission)
        db.commit()
    
    logger.info("[MissionStream] start rid=%s shop=%s mission_id=%s", rid, shop, mission_id)
    
    async def event_generator():
        """Generate SSE events as agents complete."""
        from src.main.agents import MissionControl, MissionState
        from src.main.services import ServiceRegistry
        
        # Acquire lock
        _mission_locks[mission_id] = True
        
        try:
            # Load initial state from mission record
            initial_state_dict = mission.current_state or {}
            
            state = MissionState.from_dict(initial_state_dict, db=db)
            
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
                
                # Heartbeat to keep connection alive
                yield f": heartbeat\n\n"
                
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
        
        finally:
            # Always release the lock
            _mission_locks.pop(mission_id, None)
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
    from src.main.db.db_models import Mission
    
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
    from src.main.db.db_models import Mission
    
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
        from src.main.agents import MissionControl, MissionState
        from src.main.services import ServiceRegistry
        
        # Acquire lock
        _mission_locks[mission_id] = True
        
        try:
            # Load state from mission record
            state_dict = mission.current_state or {}
            state = MissionState.from_dict(state_dict, db=db)
            
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
            # Execute single step and chain auto-proceed steps
            while True:
                async for updated_state in mission_control.execute_single_step(state):
                    # Update mission record in DB
                    try:
                        mission.current_state = updated_state.to_dict()
                        mission.status = updated_state.status
                        mission.logs = updated_state.logs
                        if updated_state.status == "COMPLETED":
                            from datetime import datetime, timezone
                            mission.completed_at = datetime.now(timezone.utc)
                        if updated_state.error_message:
                            mission.error_message = updated_state.error_message
                        db.add(mission)
                        db.commit()
                    except Exception as e:
                        logger.warning("[MissionStep] DB update failed: %s", e)
                        try:
                            db.rollback()
                        except Exception:
                            pass
                    
                    # Yield SSE event
                    state_json = json.dumps(updated_state.to_dict())
                    yield f"event: state_update\ndata: {state_json}\n\n"
                    
                    # Keep state reference updated for potential chaining
                    state = updated_state
                    
                    await asyncio.sleep(0.1)
                
                # Check if auto-proceeded (status PENDING means no gate, keep running)
                if state.status == "PENDING" and state.current_agent_index < len(mission_control.workflow):
                    # Emit auto-proceed event so frontend can update UI
                    auto_data = {
                        "mission_id": mission_id,
                        "auto_proceeded_from": state.current_agent_index - 1,
                        "next_agent_index": state.current_agent_index,
                        "next_agent": state.workflow_agents[state.current_agent_index] if state.current_agent_index < len(state.workflow_agents) else None,
                    }
                    yield f"event: step_auto_proceeded\ndata: {json.dumps(auto_data)}\n\n"
                    # Continue the loop to run the next agent immediately
                    continue
                else:
                    # Gated (AWAITING_APPROVAL), completed, or error – break
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
    from src.main.db.db_models import Mission
    from src.main.agents import MissionControl, MissionState
    from src.main.services import ServiceRegistry
    
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
        from src.main.db.db_transactions import get_shop_access_token
        from src.main.services.shopify_service import (
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
        #   (no template)        → base RewriterAgent → same as product/description
        TEMPLATE_TEMPLATES = {"product/faq", "product/landing-hero", "product/blog-post", "product/collection"}
        
        product_title = None
        product_desc = None
        blog_post_outputs = []
        faq_outputs = []
        hero_outputs = []
        collection_outputs = []
        
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
    
    from src.main.db.db_models import Mission
    from src.main.agents import MissionControl, MissionState
    from src.main.services import ServiceRegistry
    
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
    from src.main.db.db_models import Mission
    from src.main.agents import MissionControl, MissionState
    from src.main.services import ServiceRegistry
    
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
        from src.main.db.db_transactions import get_shop_access_token
        from src.main.services.shopify_service import (
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
        TEMPLATE_TEMPLATES = {"product/faq", "product/landing-hero", "product/blog-post", "product/collection"}
        
        product_title = None
        product_desc = None
        blog_post_outputs = []
        faq_outputs = []
        hero_outputs = []
        collection_outputs = []
        
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

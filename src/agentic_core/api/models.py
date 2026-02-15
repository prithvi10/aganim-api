"""
Generic Pydantic models for the agentic_core mission API.

These models define the public contract for mission CRUD operations.
Domain-specific (e.g. Shopify) endpoints may extend or wrap them.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CreateMissionRequest(BaseModel):
    """Request to create a new mission."""
    tenant_id: str = Field(..., description="Tenant / shop identifier")
    resource_id: str = Field(..., description="Product or resource ID")
    tier: str = Field(default="Basic", description="Plan tier (Basic, Growth, Pro)")
    raw_input: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary input payload")
    requested_agents: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific agent names to run",
    )
    workflow_config: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Optional Mission Architect pipeline config",
    )


class MissionResponse(BaseModel):
    """Response after creating or fetching a mission."""
    mission_id: str
    tenant_id: str
    resource_id: str
    status: str
    tier: Optional[str] = None
    current_state: Optional[Dict[str, Any]] = None
    logs: Optional[List[Any]] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class StepResponse(BaseModel):
    """Response after executing a mission step."""
    mission_id: str
    current_agent: Optional[str] = None
    current_agent_index: int = 0
    total_agents: int = 0
    status: str = "PENDING"
    agent_output: Optional[Dict[str, Any]] = None
    can_continue: bool = False
    is_final: bool = False
    workflow_agents: List[str] = Field(default_factory=list)


class AdvanceRequest(BaseModel):
    """Request to advance (continue / approve) to the next step."""
    pass


class RegenerateRequest(BaseModel):
    """Request to regenerate the current step's output."""
    feedback: Optional[str] = Field(
        default=None,
        description="Optional feedback to improve the regenerated output",
    )


class SkipRequest(BaseModel):
    """Request to skip the current step."""
    pass

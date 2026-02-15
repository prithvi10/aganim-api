"""
GenericMissionState - Domain-agnostic mission state for the agentic core.

This is the "clipboard" that agents read from and write to.
It contains only fields needed by the generic agent orchestration
framework -- no content-marketing, SEO, or domain-specific concepts.

Domain-specific extensions (e.g. ShopifyMissionState) inherit from
this and add their own fields.

Field naming convention:
    The constructor fields use legacy names (product_id, shop_id,
    plan_tier) for backward compatibility with existing constructor sites.
    Generic property aliases (resource_id, tenant_id, tier) are
    provided for new code.  The DB model and serialisation output
    both generic and legacy keys.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session


@dataclass
class GenericMissionState:
    """
    Domain-agnostic mission state that the agentic core operates on.
    """

    # Required identifiers (constructor uses legacy names for compat)
    product_id: str
    shop_id: str
    plan_tier: str
    raw_input: Dict[str, Any]

    # Database session (not serialised)
    db: Optional[Session] = None

    # Audit trail
    logs: List[str] = field(default_factory=list)

    # Mission status
    status: str = "PENDING"

    # Error tracking
    error_message: Optional[str] = None

    # Step-by-step journey tracking
    current_agent_index: int = 0
    skipped_agents: List[str] = field(default_factory=list)
    agent_outputs: Dict[str, Any] = field(default_factory=dict)
    regeneration_feedback: Optional[str] = None
    workflow_agents: List[str] = field(default_factory=list)

    # Mission Architect: merchant-defined pipeline config
    workflow_config: List[Dict[str, Any]] = field(default_factory=list)

    # Autonomous execution flag
    autonomous: bool = False

    # ------------------------------------------------------------------
    # Generic property aliases -- new code should prefer these names.
    # ------------------------------------------------------------------

    @property
    def resource_id(self) -> str:
        """Generic alias for product_id."""
        return self.product_id

    @resource_id.setter
    def resource_id(self, value: str) -> None:
        self.product_id = value

    @property
    def tenant_id(self) -> str:
        """Generic alias for shop_id."""
        return self.shop_id

    @tenant_id.setter
    def tenant_id(self, value: str) -> None:
        self.shop_id = value

    @property
    def tier(self) -> str:
        """Generic alias for plan_tier."""
        return self.plan_tier

    @tier.setter
    def tier(self, value: str) -> None:
        self.plan_tier = value

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def _generic_dict(self) -> Dict[str, Any]:
        """Return only the generic fields as a dict."""
        return {
            # Legacy names
            "product_id": self.product_id,
            "shop_id": self.shop_id,
            "plan_tier": self.plan_tier,
            # Generic aliases
            "resource_id": self.product_id,
            "tenant_id": self.shop_id,
            "tier": self.plan_tier,
            "raw_input": self.raw_input,
            "logs": self.logs,
            "status": self.status,
            "error_message": self.error_message,
            "current_agent_index": self.current_agent_index,
            "skipped_agents": self.skipped_agents,
            "agent_outputs": self.agent_outputs,
            "regeneration_feedback": self.regeneration_feedback,
            "workflow_agents": self.workflow_agents,
            "workflow_config": self.workflow_config,
            "autonomous": self.autonomous,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to a JSON-serializable dictionary."""
        return self._generic_dict()

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        db: Optional[Session] = None,
    ) -> "GenericMissionState":
        """Create a GenericMissionState from a dictionary."""
        return cls(
            shop_id=data.get("shop_id", data.get("tenant_id", "")),
            product_id=data.get("product_id", data.get("resource_id", "")),
            plan_tier=data.get("plan_tier", data.get("tier", "Free")),
            raw_input=data.get("raw_input", {}),
            db=db,
            logs=data.get("logs", []),
            status=data.get("status", "PENDING"),
            error_message=data.get("error_message"),
            current_agent_index=data.get("current_agent_index", 0),
            skipped_agents=data.get("skipped_agents", []),
            agent_outputs=data.get("agent_outputs", {}),
            regeneration_feedback=data.get("regeneration_feedback"),
            workflow_agents=data.get("workflow_agents", []),
            workflow_config=data.get("workflow_config", []),
            autonomous=data.get("autonomous", False),
        )

    def add_log(self, message: str) -> None:
        """Add a log message to the audit trail."""
        self.logs.append(message)

    def set_error(self, message: str) -> None:
        """Set error status with message."""
        self.status = "ERROR"
        self.error_message = message
        self.logs.append(f"ERROR: {message}")

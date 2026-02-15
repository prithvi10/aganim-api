"""
InProcessAgenticPlatform - In-process implementation of AgenticPlatformAPI.

This is the concrete adapter that wires MissionControl, ServiceRegistry,
and the agent registry into a single facade.

Today it lives in-process.  Tomorrow the *same* Protocol can be backed by
an HTTP/gRPC client that talks to a standalone agentic micro-service.
"""

from __future__ import annotations

import uuid
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    Type,
)

from .agents.base import BaseAgent
from .agents.orchestrator import MissionControl
from .agents.state import GenericMissionState
from .registry import ServiceRegistry
from src.shared.logging.logger import get_logger

from .interfaces import (
    AgenticPlatformAPI,
    CostRecorder,
    PublishAdapter,
    UsageCallback,
)

logger = get_logger(__name__)


class InProcessAgenticPlatform:
    """
    In-process implementation of :class:`AgenticPlatformAPI`.

    Holds a mutable agent registry and tool registry so that consumers
    can extend the platform at boot time.
    """

    def __init__(
        self,
        services: ServiceRegistry,
        cost_recorder: Optional[CostRecorder] = None,
        state_factory: Optional[Callable[..., GenericMissionState]] = None,
        agent_map: Optional[Dict[str, Type[BaseAgent]]] = None,
    ) -> None:
        self._services = services
        self._cost_recorder = cost_recorder
        self._state_factory = state_factory or GenericMissionState.from_dict

        # Mutable registries
        self._agent_map: Dict[str, Type[BaseAgent]] = dict(agent_map or {})
        self._tool_registry: Dict[str, Any] = {}

        # In-flight missions keyed by mission_id → MissionControl
        self._missions: Dict[str, MissionControl] = {}

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def create_default(
        cls,
        publish_adapter: Optional[PublishAdapter] = None,
        cost_recorder: Optional[CostRecorder] = None,
        state_factory: Optional[Callable[..., GenericMissionState]] = None,
        agent_map: Optional[Dict[str, Type[BaseAgent]]] = None,
        db: Any = None,
        shop_domain: Optional[str] = None,
    ) -> "InProcessAgenticPlatform":
        """Convenience factory that builds ServiceRegistry internally."""
        services = ServiceRegistry.create_default(db=db, shop_domain=shop_domain)
        if publish_adapter is not None:
            services.publish_adapter = publish_adapter
        return cls(
            services=services,
            cost_recorder=cost_recorder,
            state_factory=state_factory,
            agent_map=agent_map,
        )

    @classmethod
    def create_generic(cls) -> "InProcessAgenticPlatform":
        """Minimal platform for non-Shopify consumers."""
        return cls(services=ServiceRegistry.create_generic())

    # ==================================================================
    # AgenticPlatformAPI — Mission lifecycle
    # ==================================================================

    async def create_mission(
        self,
        tenant_id: str,
        resource_id: str,
        tier: str,
        raw_input: Dict[str, Any],
        workflow_config: Optional[List[Dict[str, Any]]] = None,
        requested_agents: Optional[List[str]] = None,
    ) -> str:
        """Create a mission and return its ID."""
        mission_id = uuid.uuid4().hex

        mc = MissionControl(
            plan_tier=tier,
            shop_id=tenant_id,
            services=self._services,
            requested_agents=requested_agents,
            mission_id=mission_id,
            workflow_config=workflow_config,
            cost_recorder=self._cost_recorder,
            agent_map=self._agent_map or None,
        )
        self._missions[mission_id] = mc

        logger.info(
            "[Platform] created mission=%s tenant=%s agents=%s",
            mission_id,
            tenant_id,
            [a.__name__ for a in mc.workflow],
        )
        return mission_id

    async def execute_step(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
        db: Any = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute the current step, yielding state dicts for SSE."""
        mc = self._get_mission(mission_id)
        state = self._state_factory(state_dict, db)

        async for updated in mc.execute_single_step(state):
            yield updated.to_dict()

    async def advance_step(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
        db: Any = None,
    ) -> Dict[str, Any]:
        """Advance to the next step after approval."""
        mc = self._get_mission(mission_id)
        state = self._state_factory(state_dict, db)
        updated = await mc.advance_to_next_step(state)
        return updated.to_dict()

    async def skip_step(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
        db: Any = None,
    ) -> Dict[str, Any]:
        """Skip the current step."""
        mc = self._get_mission(mission_id)
        state = self._state_factory(state_dict, db)
        updated = mc.skip_current_step(state)
        return updated.to_dict()

    async def regenerate_step(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
        feedback: Optional[str] = None,
        db: Any = None,
    ) -> Dict[str, Any]:
        """Regenerate the current step with optional feedback."""
        mc = self._get_mission(mission_id)
        state = self._state_factory(state_dict, db)
        updated = mc.prepare_regeneration(state, feedback=feedback)
        return updated.to_dict()

    # ==================================================================
    # Full mission execution (auto-flow)
    # ==================================================================

    async def execute_mission(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
        db: Any = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Run the full agent workflow, yielding state dicts for SSE."""
        mc = self._get_mission(mission_id)
        state = self._state_factory(state_dict, db)

        async for updated in mc.execute(state):
            yield updated.to_dict()

    # ==================================================================
    # Agent registry
    # ==================================================================

    def register_agent(self, name: str, agent_class: Any) -> None:
        """Register a new agent type."""
        self._agent_map[name] = agent_class
        logger.info("[Platform] registered agent '%s' → %s", name, agent_class.__name__)

    def list_agents(self) -> List[str]:
        """List all registered agent names."""
        return list(self._agent_map.keys())

    # ==================================================================
    # Tool registry
    # ==================================================================

    def register_tool(self, name: str, tool_instance: Any) -> None:
        """Register a new tool/service."""
        self._tool_registry[name] = tool_instance
        logger.info("[Platform] registered tool '%s'", name)

    def get_tool(self, name: str) -> Optional[Any]:
        """Retrieve a registered tool by name."""
        return self._tool_registry.get(name)

    # ==================================================================
    # RAG
    # ==================================================================

    async def ingest_context(
        self,
        tenant_id: str,
        texts: List[str],
        metadata: Optional[List[dict]] = None,
    ) -> None:
        """Ingest text chunks into the RAG knowledge base."""
        rag = self._services.rag
        if rag is None:
            raise RuntimeError("RAG service not configured")
        logger.warning(
            "[Platform] ingest_context is a stub – extend RAGService.ingest() "
            "for full support"
        )

    async def query_context(
        self,
        tenant_id: str,
        query_text: str,
        limit: int = 5,
    ) -> List[dict]:
        """Query the RAG knowledge base for relevant context."""
        rag = self._services.rag
        if rag is None:
            raise RuntimeError("RAG service not configured")
        logger.warning(
            "[Platform] query_context called without db session – "
            "consider using RAGService directly with a db session"
        )
        return []

    # ==================================================================
    # Workflow introspection
    # ==================================================================

    def get_workflow_info(self, mission_id: str) -> dict:
        """Get workflow metadata for a mission."""
        mc = self._get_mission(mission_id)
        return mc.get_workflow_info()

    def remove_mission(self, mission_id: str) -> None:
        """Remove a mission from the in-memory cache."""
        self._missions.pop(mission_id, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_mission(self, mission_id: str) -> MissionControl:
        mc = self._missions.get(mission_id)
        if mc is None:
            raise KeyError(
                f"Mission '{mission_id}' not found in platform cache. "
                "Was it created via create_mission()?"
            )
        return mc

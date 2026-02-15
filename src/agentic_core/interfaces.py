"""
Agentic Core Interfaces - Protocol definitions for the AI platform boundary.

These protocols define the contract between the generic agentic core and any
domain-specific consumer (Shopify, financial analysis, real-estate CRM, etc.).

Consumers implement these protocols and inject them into the agentic core
via ServiceRegistry or MissionControl constructor parameters.
"""

from __future__ import annotations

from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)


# =============================================================================
# Publish Adapter Protocol
# =============================================================================

@runtime_checkable
class PublishAdapter(Protocol):
    """
    Adapter for pushing approved agent outputs to external systems.
    """

    async def get_credentials(self, db: Any, tenant_id: str) -> dict:
        """Retrieve credentials needed for publishing."""
        ...

    async def publish(
        self,
        state: Any,
        template_id: str,
        handler_ref: Any,
        creds: dict,
    ) -> Tuple[bool, Optional[str]]:
        """Execute the publish action."""
        ...


# =============================================================================
# Usage Callback
# =============================================================================

# Called by LLMService after each LLM call to record token usage.
# Signature: (usage_dict: dict) -> None
UsageCallback = Callable[[dict], None]


# =============================================================================
# Cost Recorder Callback
# =============================================================================

# Called by MissionControl after mission completion to record accumulated costs.
# Signature: (tenant_id: str, accumulated_usage: dict, db: Any) -> None
CostRecorder = Callable[[str, dict, Any], None]


# =============================================================================
# Agentic Platform API Protocol
# =============================================================================

@runtime_checkable
class AgenticPlatformAPI(Protocol):
    """
    Contract for what any consumer can ask the AI platform to do.

    Today this is implemented as in-process function calls.
    Tomorrow it can be swapped for an HTTP/gRPC client.
    """

    # ---- Mission lifecycle ----

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
        ...

    async def execute_step(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
        db: Any = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute the current step, yielding state updates for SSE."""
        ...

    async def advance_step(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Advance to the next step after approval."""
        ...

    async def skip_step(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Skip the current step."""
        ...

    async def regenerate_step(
        self,
        mission_id: str,
        state_dict: Dict[str, Any],
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Regenerate the current step with optional feedback."""
        ...

    # ---- Agent registry ----

    def register_agent(self, name: str, agent_class: Any) -> None:
        """Register a new agent type."""
        ...

    def list_agents(self) -> List[str]:
        """List all registered agent names."""
        ...

    # ---- Tool registry ----

    def register_tool(self, name: str, tool_instance: Any) -> None:
        """Register a new tool/service."""
        ...

    # ---- RAG ----

    async def ingest_context(
        self,
        tenant_id: str,
        texts: List[str],
        metadata: Optional[List[dict]] = None,
    ) -> None:
        """Ingest text chunks into the RAG knowledge base."""
        ...

    async def query_context(
        self,
        tenant_id: str,
        query_text: str,
        limit: int = 5,
    ) -> List[dict]:
        """Query the RAG knowledge base for relevant context."""
        ...


# =============================================================================
# RAG Storage Adapter Protocol
# =============================================================================

@runtime_checkable
class RAGStorageAdapter(Protocol):
    """
    Adapter for domain-specific RAG operations that depend on models outside
    the generic ``agentic_core`` boundary (e.g. ``Shop``, ``BrandEntity``).

    The generic :class:`RAGService` delegates these calls to the adapter so
    that its core vector-search logic stays decoupled from any e-commerce or
    domain-specific ORM models.
    """

    async def get_strategic_intelligence(
        self, db: Any, tenant_id: str,
    ) -> Optional[Dict]:
        """Return strategic intelligence JSON for *tenant_id*, or ``None``."""
        ...

    async def get_tenant_summary(
        self, db: Any, tenant_id: str,
    ) -> Optional[Dict]:
        """Return a brand/tenant summary dict, or ``None``."""
        ...

    async def traverse_knowledge_graph(
        self,
        db: Any,
        tenant_id: str,
        seed_entities: List[str],
        depth: int = 2,
    ) -> List[Dict]:
        """Traverse the knowledge graph starting from *seed_entities*."""
        ...

"""
BaseAgent - Abstract base class for all agents.

Implements the standard agentic loop:
1. PERCEPTION  - Gather context from environment
2. REASONING   - Analyze and plan (deterministic by default)
3. ACTION      - Execute tools/services
4. FEEDBACK    - Learn from outcomes
"""

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from .state import GenericMissionState
from .context import AgentContext, AgentPlan, AgentAction
from .memory import AgentMemoryService
from src.shared.logging.logger import get_logger

if TYPE_CHECKING:
    from src.agentic_core.registry import ServiceRegistry

# Use GenericMissionState as the type hint name "MissionState" within this module
# for readability. Domain-specific subclasses (ShopifyMissionState) are accepted
# transparently because they inherit from GenericMissionState.
MissionState = GenericMissionState

logger = get_logger(__name__)


class BaseAgent(ABC):
    """
    Base class for all agents following the standard agentic loop.
    
    The loop consists of four phases:
    
    1. PERCEPTION  - Gather context from environment (state, RAG, external APIs)
    2. REASONING   - Analyze context and plan actions (deterministic OR LLM-based)
    3. ACTION      - Execute tools/services to produce output
    4. FEEDBACK    - Learn from outcomes for future improvement
    
    COST OPTIMIZATION:
    By default, the Reasoning phase uses deterministic logic (no LLM call).
    Set `requires_llm_reasoning = True` for complex multi-step workflows.
    This keeps most agents at 1 LLM call (in Action phase only).
    
    Subclasses must implement:
    - _perceive_domain(): Domain-specific context gathering
    - _act_domain(): Domain-specific action execution (LLM call here)
    
    Optional overrides:
    - _create_default_plan(): Custom deterministic planning
    - _reason_with_llm(): LLM-based planning (if requires_llm_reasoning=True)
    - _feedback_domain(): Domain-specific learning
    """
    
    # Class attributes - override in subclasses
    role_name: str = "BaseAgent"
    
    # Cost optimization: most agents don't need LLM for planning
    requires_llm_reasoning: bool = False
    
    # Default tool to use in deterministic plan
    default_tool: str = "llm.generate_text"
    
    # Publish map: template_id → async handler(self, state, creds) -> None
    # Override in subclasses to register autonomous publish handlers.
    PUBLISH_MAP: Dict[str, Callable] = {}

    def __init__(self, shop_id: str, services: "ServiceRegistry"):
        """
        Initialize the agent.
        
        Args:
            shop_id: Shop domain identifier
            services: ServiceRegistry with LLM, SERP, RAG services
        """
        self.shop_id = shop_id
        self.services = services
        self.memory = AgentMemoryService(shop_id)

    async def run(self, state: MissionState) -> MissionState:
        """
        Main execution loop following Perception → Reasoning → Action → Feedback.
        """
        # Attach db session to memory service if available
        if state.db:
            self.memory.db = state.db

        try:
            # 1. PERCEPTION: Gather all context needed for this task
            state.add_log(f"{self.role_name}: Perceiving environment...")
            context = await self.perceive(state)
            
            # 2. REASONING: Create execution plan (deterministic by default)
            state.add_log(f"{self.role_name}: Planning...")
            plan = await self.reason(state, context)
            
            # 3. ACTION: Execute the plan using available tools/services
            state.add_log(f"{self.role_name}: Executing...")
            actions, new_state = await self.act(state, context, plan)
            
            # 4. FEEDBACK: Record outcomes for learning
            await self.feedback(state, new_state, actions)
            new_state.add_log(f"{self.role_name}: Completed.")
            
            return new_state
            
        except Exception as e:
            logger.error(
                "[%s] Error during execution shop=%s err=%s",
                self.role_name,
                self.shop_id,
                e,
            )
            state.set_error(f"{self.role_name} failed: {str(e)}")
            return state

    # -------------------------------------------------------------------------
    # PERCEPTION
    # -------------------------------------------------------------------------
    async def perceive(self, state: MissionState) -> AgentContext:
        """Gather context from environment."""
        learned_rules = await self.memory.get_learned_preferences(self.role_name)
        
        brand_soul_enabled = (state.raw_input or {}).get("brand_soul_enabled", True)

        strategic_intel = None
        if brand_soul_enabled and state.db:
            try:
                strategic_intel = await self.services.rag.get_strategic_intelligence(
                    state.db,
                    self.shop_id,
                )
            except Exception as e:
                logger.warning(
                    "[%s] Failed to load strategic intelligence shop=%s err=%s",
                    self.role_name,
                    self.shop_id,
                    e,
                )
        
        context = AgentContext(
            raw_input=state.raw_input,
            learned_rules=learned_rules,
            strategic_intelligence=strategic_intel,
        )
        
        return await self._perceive_domain(state, context)

    @abstractmethod
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """Subclass hook: Add domain-specific context gathering."""
        pass

    # -------------------------------------------------------------------------
    # REASONING
    # -------------------------------------------------------------------------
    async def reason(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentPlan:
        """Create an execution plan (deterministic by default)."""
        if self.requires_llm_reasoning:
            return await self._reason_with_llm(state, context)
        return self._create_default_plan(state, context)

    def _create_default_plan(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentPlan:
        """Create a simple deterministic plan."""
        return AgentPlan(
            steps=["execute_primary_action"],
            selected_tools=[self.default_tool],
            confidence=1.0,
            reasoning=f"Standard {self.role_name} execution",
        )

    async def _reason_with_llm(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentPlan:
        """Use LLM for sophisticated planning (only when requires_llm_reasoning=True)."""
        return self._create_default_plan(state, context)

    # -------------------------------------------------------------------------
    # ACTION
    # -------------------------------------------------------------------------
    async def act(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """Execute the planned actions using services."""
        return await self._act_domain(state, context, plan)

    @abstractmethod
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """Subclass hook: Execute domain-specific actions."""
        pass

    # -------------------------------------------------------------------------
    # FEEDBACK
    # -------------------------------------------------------------------------
    async def feedback(
        self,
        old_state: MissionState,
        new_state: MissionState,
        actions: List[AgentAction],
    ) -> None:
        """Record outcomes for future learning."""
        for action in actions:
            if not action.success:
                await self.memory.record_failure(
                    self.role_name,
                    action.tool_name,
                    action.error,
                )
        await self._feedback_domain(old_state, new_state, actions)

    async def _feedback_domain(
        self,
        old_state: MissionState,
        new_state: MissionState,
        actions: List[AgentAction],
    ) -> None:
        """Subclass hook: Domain-specific feedback/learning. Optional."""
        pass

    # -------------------------------------------------------------------------
    # AUTONOMOUS PUBLISH
    # -------------------------------------------------------------------------
    async def _maybe_publish(
        self,
        state: MissionState,
        template_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to publish approved content via the publish_adapter.

        Only acts when ``state.autonomous`` is True and a matching handler
        exists in ``PUBLISH_MAP``.
        """
        if not state.autonomous:
            return False, None

        if not template_id:
            return False, None

        handler_ref = self.PUBLISH_MAP.get(template_id)
        if handler_ref is None:
            # Check for wildcard prefix matches (e.g. "marketing/email-*")
            for pattern, h in self.PUBLISH_MAP.items():
                if pattern.endswith("*") and template_id.startswith(pattern[:-1]):
                    handler_ref = h
                    break

        if handler_ref is None:
            logger.debug(
                "[%s] No publish handler for template_id=%s",
                self.role_name,
                template_id,
            )
            return False, None

        # Resolve handler: can be a method name (str) or a callable
        if isinstance(handler_ref, str):
            handler = getattr(self, handler_ref, None)
            if handler is None:
                return False, f"publish handler '{handler_ref}' not found on {self.role_name}"
        else:
            handler = handler_ref

        # Delegate credential loading to the publish adapter
        publish_adapter = getattr(self.services, "publish_adapter", None)
        if publish_adapter is None:
            logger.debug(
                "[%s] No publish_adapter configured – skipping publish",
                self.role_name,
            )
            return False, None

        creds = {}
        if state.db:
            creds = await publish_adapter.get_credentials(state.db, state.shop_id)

        if not creds.get("access_token"):
            state.add_log(f"{self.role_name}: Publish skipped – missing shop credentials")
            return False, "missing_credentials"

        try:
            await handler(state, creds)
            state.add_log(
                f"{self.role_name}: ✅ Published via {template_id}"
            )
            logger.info(
                "[%s] Published template=%s shop=%s",
                self.role_name,
                template_id,
                state.shop_id,
            )
            return True, None
        except Exception as e:
            error_msg = str(e)
            state.add_log(
                f"{self.role_name}: ❌ Publish failed for {template_id}: {error_msg}"
            )
            logger.error(
                "[%s] Publish failed template=%s shop=%s err=%s",
                self.role_name,
                template_id,
                state.shop_id,
                error_msg,
            )
            return False, error_msg

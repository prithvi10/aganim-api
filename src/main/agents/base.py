"""
BaseAgent - Abstract base class for all agents.

Implements the standard agentic loop:
1. PERCEPTION  - Gather context from environment
2. REASONING   - Analyze and plan (deterministic by default)
3. ACTION      - Execute tools/services
4. FEEDBACK    - Learn from outcomes
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, TYPE_CHECKING

from .state import MissionState
from .context import AgentContext, AgentPlan, AgentAction
from .memory import AgentMemoryService
from src.main.logging.logger import get_logger

if TYPE_CHECKING:
    from src.main.services import ServiceRegistry

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
    
    Usage:
        class MyAgent(BaseAgent):
            role_name = "MyAgent"
            default_tool = "llm.generate_text"
            
            async def _perceive_domain(self, state, context):
                # Gather domain-specific context
                return context
            
            async def _act_domain(self, state, context, plan):
                # Execute the main action (LLM call)
                result = await self.services.llm.generate_text(...)
                state.draft_content = result
                return [AgentAction(...)], state
    """
    
    # Class attributes - override in subclasses
    role_name: str = "BaseAgent"
    
    # Cost optimization: most agents don't need LLM for planning
    requires_llm_reasoning: bool = False
    
    # Default tool to use in deterministic plan
    default_tool: str = "llm.generate_text"

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
        
        Args:
            state: Current mission state
        
        Returns:
            Updated mission state after agent processing
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
    # PERCEPTION: Sense inputs from environment (no LLM call)
    # -------------------------------------------------------------------------
    async def perceive(self, state: MissionState) -> AgentContext:
        """
        Gather context from environment.
        
        This phase collects all information needed for the agent to do its work:
        - Current state (raw product data)
        - Brand context via RAG
        - Learned preferences from memory
        - External data (SERP, APIs) if needed
        
        NOTE: This phase does NOT call LLM - it only gathers data.
        
        Args:
            state: Current mission state
        
        Returns:
            AgentContext with all gathered information
        """
        # Base perception: get learned rules from memory
        learned_rules = await self.memory.get_learned_preferences(self.role_name)
        
        # Get strategic intelligence if available
        strategic_intel = None
        if state.db:
            try:
                strategic_intel = await self.services.rag._get_strategic_intelligence(
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
        
        # Let subclasses add domain-specific perception (RAG, SERP, etc.)
        return await self._perceive_domain(state, context)

    @abstractmethod
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """
        Subclass hook: Add domain-specific context gathering.
        
        Examples:
        - CopywriterAgent: Fetch brand context via RAG
        - PriceScoutAgent: Fetch competitor data via SERP
        - ComplianceAgent: Run regex pre-scan
        
        Args:
            state: Current mission state
            context: Context with base perception done
        
        Returns:
            Context with domain-specific data added
        """
        pass

    # -------------------------------------------------------------------------
    # REASONING: Plan actions (DETERMINISTIC by default, LLM optional)
    # -------------------------------------------------------------------------
    async def reason(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentPlan:
        """
        Create an execution plan.
        
        COST OPTIMIZATION:
        - Default: Returns deterministic plan (NO LLM call)
        - Override `requires_llm_reasoning = True` for complex workflows
        - Pro tier can enable LLM reasoning for sophisticated planning
        
        Args:
            state: Current mission state
            context: Context from perception phase
        
        Returns:
            AgentPlan describing what actions to take
        """
        # Check if this agent needs LLM-based reasoning
        if self.requires_llm_reasoning:
            return await self._reason_with_llm(state, context)
        
        # Default: deterministic plan (no LLM cost)
        return self._create_default_plan(state, context)

    def _create_default_plan(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentPlan:
        """
        Create a simple deterministic plan.
        
        Override in subclass for custom deterministic logic.
        
        Args:
            state: Current mission state
            context: Context from perception
        
        Returns:
            Simple plan with default tool
        """
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
        """
        Use LLM for sophisticated planning.
        
        Only called when requires_llm_reasoning = True.
        Override in subclass for custom LLM-based reasoning.
        
        Args:
            state: Current mission state
            context: Context from perception
        
        Returns:
            Plan created by LLM analysis
        """
        # Default implementation - subclasses can override
        return self._create_default_plan(state, context)

    # -------------------------------------------------------------------------
    # ACTION: Execute tools and produce output (PRIMARY LLM CALL HERE)
    # -------------------------------------------------------------------------
    async def act(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Execute the planned actions using services.
        
        THIS IS WHERE THE LLM CALL HAPPENS for most agents:
        - LLMService.generate_text() for creative content
        - LLMService.generate_structured() for deterministic outputs
        - SerpService for competitor data (already gathered in Perception)
        
        Args:
            state: Current mission state
            context: Context from perception
            plan: Plan from reasoning
        
        Returns:
            Tuple of (actions taken, updated state)
        """
        return await self._act_domain(state, context, plan)

    @abstractmethod
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Subclass hook: Execute domain-specific actions.
        
        This is where the main LLM call happens.
        
        Args:
            state: Current mission state
            context: Context from perception
            plan: Plan from reasoning
        
        Returns:
            Tuple of (actions taken, updated state)
        """
        pass

    # -------------------------------------------------------------------------
    # FEEDBACK: Learn from outcomes (no LLM call)
    # -------------------------------------------------------------------------
    async def feedback(
        self,
        old_state: MissionState,
        new_state: MissionState,
        actions: List[AgentAction],
    ) -> None:
        """
        Record outcomes for future learning.
        
        This phase records what happened so the agent can improve:
        - Log successful/failed actions
        - Store patterns for memory retrieval
        - Update confidence metrics
        
        NOTE: This phase does NOT call LLM - it only records data.
        
        Args:
            old_state: State before action
            new_state: State after action
            actions: Actions that were executed
        """
        # Base feedback: log action outcomes
        for action in actions:
            if not action.success:
                await self.memory.record_failure(
                    self.role_name,
                    action.tool_name,
                    action.error,
                )
        
        # Let subclasses add domain-specific feedback
        await self._feedback_domain(old_state, new_state, actions)

    async def _feedback_domain(
        self,
        old_state: MissionState,
        new_state: MissionState,
        actions: List[AgentAction],
    ) -> None:
        """
        Subclass hook: Domain-specific feedback/learning.
        
        Optional - only override if the agent needs special learning logic.
        
        Args:
            old_state: State before action
            new_state: State after action
            actions: Actions that were executed
        """
        pass

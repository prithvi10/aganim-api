"""
MissionControl - Orchestrator for the multi-agent workflow.

This is the central coordinator that:
- Routes missions based on plan tier
- Supports ad-hoc agent execution (run specific agents only)
- Executes agents in sequence
- Handles the adversarial loop for compliance
- Yields state updates for SSE streaming
- Records token usage for fair_use cost tracking
"""

from typing import List, Type, AsyncGenerator, Optional
import uuid
from datetime import datetime

from .base import BaseAgent
from .state import MissionState
from .copywriter import CopywriterAgent
from .seo import SEOAgent
from .marketing import MarketingAgent
from .price_scout import PriceScoutAgent
from .compliance import ComplianceAgent  # Kept for reference but disabled
from src.main.services import ServiceRegistry
from src.main.services.fair_use_service import record_cost_from_usage
from src.main.logging.logger import get_logger

logger = get_logger(__name__)

# Agent name to class mapping for ad-hoc agent selection
# NOTE: ComplianceAgent is disabled until further notice
AGENT_MAP = {
    "CopywriterAgent": CopywriterAgent,
    "SEOAgent": SEOAgent,
    "MarketingAgent": MarketingAgent,
    "PriceScoutAgent": PriceScoutAgent,
    # "ComplianceAgent": ComplianceAgent,  # DISABLED
}


class MissionControl:
    """
    Orchestrator for the multi-agent product optimization workflow.
    
    Responsibilities:
    - Plan-based routing (Basic vs Standard vs Pro workflows)
    - Sequential agent execution
    - Adversarial loop handling (compliance rejection → regeneration)
    - State streaming for SSE
    - Mission persistence
    
    Usage:
        services = ServiceRegistry.create_default()
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="my-shop.myshopify.com",
            services=services,
        )
        
        async for state in mission.execute(initial_state):
            # Stream state updates to frontend via SSE
            yield f"data: {json.dumps(state.to_dict())}\\n\\n"
    """

    # Agent workflow configurations per plan tier
    # NOTE: All tiers get full agent pipeline - usage limited by product count, not features
    # Workflow: Copywriter → SEO → Marketing → PriceScout
    # ComplianceAgent is DISABLED until further notice
    WORKFLOWS = {
        "Free": [CopywriterAgent, SEOAgent, MarketingAgent, PriceScoutAgent],
        "Basic": [CopywriterAgent, SEOAgent, MarketingAgent, PriceScoutAgent],
        "Standard": [CopywriterAgent, SEOAgent, MarketingAgent, PriceScoutAgent],
        "Pro": [CopywriterAgent, SEOAgent, MarketingAgent, PriceScoutAgent],
    }
    
    # Maximum adversarial iterations for compliance (DISABLED)
    MAX_ADVERSARIAL_ITERATIONS = 0  # Disabled

    def __init__(
        self,
        plan_tier: str,
        shop_id: str,
        services: ServiceRegistry,
        requested_agents: Optional[List[str]] = None,
        mission_id: Optional[str] = None,
    ):
        """
        Initialize MissionControl.
        
        Args:
            plan_tier: User's subscription tier (Free, Basic, Standard, Pro)
            shop_id: Shop domain identifier
            services: ServiceRegistry with injected services
            requested_agents: Optional list of agent names for ad-hoc execution
                              e.g., ["CopywriterAgent"], ["MarketingAgent", "ComplianceAgent"]
                              If provided, only these agents will run instead of the tier workflow.
            mission_id: Optional mission ID from the database. If not provided, a new one is generated.
        """
        self.plan_tier = plan_tier
        self.shop_id = shop_id
        self.services = services
        self.requested_agents = requested_agents
        self.workflow = self._build_workflow()
        self.mission_id = mission_id or uuid.uuid4().hex

    def _build_workflow(self) -> List[Type[BaseAgent]]:
        """
        Build the agent workflow based on plan tier or ad-hoc agent selection.
        
        If requested_agents is provided, only those agents will be included.
        Otherwise, uses the tier-based workflow configuration.
        
        Returns:
            List of agent classes to execute in order
        """
        # Ad-hoc mode: use only the requested agents
        if self.requested_agents:
            workflow = []
            for agent_name in self.requested_agents:
                if agent_name in AGENT_MAP:
                    workflow.append(AGENT_MAP[agent_name])
                else:
                    logger.warning(
                        "[MissionControl] Unknown agent requested: %s (skipped)",
                        agent_name
                    )
            if workflow:
                logger.info(
                    "[MissionControl] Ad-hoc mode: running agents %s",
                    [a.__name__ for a in workflow]
                )
                return workflow
            # Fallback to tier workflow if no valid agents specified
            logger.warning(
                "[MissionControl] No valid agents in requested_agents, falling back to tier workflow"
            )
        
        # Default: tier-based workflow
        return self.WORKFLOWS.get(self.plan_tier, [CopywriterAgent])
    
    def _record_fair_use_costs(self, state: MissionState) -> None:
        """
        Record accumulated LLM costs to fair_use service.
        
        This is called after mission completion (success or error) to ensure
        all LLM usage is tracked for cost management.
        
        Args:
            state: The mission state (used to get db session and store usage info)
        """
        try:
            # Get accumulated usage from LLMService
            accumulated = self.services.llm.get_accumulated_usage()
            
            if accumulated.total_tokens == 0:
                logger.debug("[MissionControl] No LLM usage to record for mission=%s", self.mission_id)
                return
            
            # Store usage info in state for auditing
            state.accumulated_usage = accumulated.to_dict()
            
            # Record costs to fair_use service if we have a db session
            if state.db:
                # Determine the primary model used (use the most capable one)
                model_used = "gpt-4o"  # Default
                if accumulated.models_used:
                    # Prefer gpt-4o over gpt-4o-mini
                    if "gpt-4o" in accumulated.models_used:
                        model_used = "gpt-4o"
                    else:
                        model_used = accumulated.models_used[0]
                
                # Create usage dict compatible with fair_use_service
                usage_dict = {
                    "prompt_tokens": accumulated.prompt_tokens,
                    "completion_tokens": accumulated.completion_tokens,
                    "reasoning_tokens": accumulated.reasoning_tokens,
                    "total_tokens": accumulated.total_tokens,
                }
                
                monthly_cost = record_cost_from_usage(
                    db=state.db,
                    shop_domain=self.shop_id,
                    usage=usage_dict,
                    model_used=model_used,
                )
                
                logger.info(
                    "[MissionControl] Recorded fair_use costs mission=%s shop=%s "
                    "total_tokens=%d calls=%d models=%s monthly_cost=%.4f",
                    self.mission_id,
                    self.shop_id,
                    accumulated.total_tokens,
                    accumulated.call_count,
                    accumulated.models_used,
                    monthly_cost,
                )
                
                state.add_log(
                    f"MissionControl: Recorded {accumulated.total_tokens} tokens "
                    f"({accumulated.call_count} LLM calls)"
                )
            else:
                logger.warning(
                    "[MissionControl] No db session - skipping fair_use recording "
                    "mission=%s tokens=%d",
                    self.mission_id,
                    accumulated.total_tokens,
                )
            
            # Reset usage tracking for next mission
            self.services.llm.reset_usage()
            
        except Exception as e:
            logger.error(
                "[MissionControl] Failed to record fair_use costs mission=%s error=%s",
                self.mission_id,
                str(e),
            )

    async def execute(
        self,
        state: MissionState,
    ) -> AsyncGenerator[MissionState, None]:
        """
        Execute the mission workflow, yielding state after each agent.
        
        This is the main execution loop that:
        1. Runs each agent in sequence
        2. Yields state updates for SSE streaming
        3. Handles adversarial loops for Pro tier
        
        Args:
            state: Initial mission state with product data
        
        Yields:
            MissionState after each agent completes
        """
        state.status = "IN_PROGRESS"
        state.add_log(f"MissionControl: Starting {self.plan_tier} workflow")
        yield state

        try:
            for agent_class in self.workflow:
                # Instantiate agent with services
                agent = agent_class(self.shop_id, services=self.services)
                
                state.add_log(f"MissionControl: Running {agent.role_name}...")
                state = await agent.run(state)
                
                # Adversarial loop for Pro tier with compliance issues (DISABLED)
                # NOTE: ComplianceAgent is currently disabled, so this code path won't execute
                # if (
                #     self.plan_tier == "Pro"
                #     and agent.role_name == "Compliance"
                #     and state.compliance_flags
                # ):
                #     state = await self._handle_adversarial_loop(state)
                pass  # Placeholder for disabled compliance adversarial loop
                
                # Yield state update after each agent
                yield state
                
                # Early exit on error
                if state.status == "ERROR":
                    logger.error(
                        "[MissionControl] Workflow halted on error mission=%s shop=%s",
                        self.mission_id,
                        self.shop_id,
                    )
                    return

            # Mark mission as complete
            if state.status != "ERROR":
                if state.compliance_flags:
                    state.status = "COMPLIANCE_REVIEW"
                else:
                    state.status = "COMPLETED"
            
            # Record fair_use costs from accumulated LLM usage
            self._record_fair_use_costs(state)
                    
            state.add_log("MissionControl: Workflow completed")
            logger.info(
                "[MissionControl] Completed mission=%s shop=%s status=%s",
                self.mission_id,
                self.shop_id,
                state.status,
            )
            yield state

        except Exception as e:
            logger.exception(
                "[MissionControl] Workflow failed mission=%s shop=%s",
                self.mission_id,
                self.shop_id,
            )
            state.set_error(f"Workflow error: {str(e)}")
            
            # Still record costs even on error (LLM calls were made)
            self._record_fair_use_costs(state)
            yield state

    async def _handle_adversarial_loop(
        self,
        state: MissionState,
    ) -> MissionState:
        """
        Handle adversarial loop: Compliance rejection → Copywriter regeneration.
        
        For Pro tier, if compliance issues are found, we ask the Copywriter
        to regenerate with the compliance feedback, then re-check.
        
        Args:
            state: Current state with compliance flags
        
        Returns:
            Updated state after adversarial resolution
        """
        iteration = 0
        
        while state.compliance_flags and iteration < self.MAX_ADVERSARIAL_ITERATIONS:
            iteration += 1
            state.add_log(
                f"MissionControl: Adversarial iteration {iteration} - "
                f"regenerating for compliance ({len(state.compliance_flags)} flags)"
            )
            
            # Add compliance feedback to raw_input for copywriter
            compliance_feedback = "\n".join([
                f"- {flag}" for flag in state.compliance_flags
            ])
            state.raw_input["compliance_feedback"] = compliance_feedback
            state.raw_input["_regeneration_attempt"] = iteration
            
            # Clear compliance flags for re-check
            state.compliance_flags = []
            
            # Re-run copywriter with compliance context
            copywriter = CopywriterAgent(self.shop_id, services=self.services)
            state = await copywriter.run(state)
            
            if state.status == "ERROR":
                break
            
            # Re-run compliance check
            compliance = ComplianceAgent(self.shop_id, services=self.services)
            state = await compliance.run(state)
        
        if iteration > 0:
            state.add_log(
                f"MissionControl: Adversarial loop completed after {iteration} iterations"
            )
            
            if state.compliance_flags:
                logger.warning(
                    "[MissionControl] Compliance issues remain after %d iterations mission=%s",
                    iteration,
                    self.mission_id,
                )
        
        return state

    async def execute_single_agent(
        self,
        agent_class: Type[BaseAgent],
        state: MissionState,
    ) -> MissionState:
        """
        Execute a single agent (useful for testing or partial reruns).
        
        Args:
            agent_class: The agent class to run
            state: Current mission state
        
        Returns:
            Updated state after agent execution
        """
        agent = agent_class(self.shop_id, services=self.services)
        return await agent.run(state)

    async def execute_single_step(
        self,
        state: MissionState,
    ) -> AsyncGenerator[MissionState, None]:
        """
        Execute only the current agent in the workflow (step-by-step mode).
        
        This allows merchants to review each agent's output before proceeding.
        After the agent completes, status is set to AWAITING_APPROVAL.
        
        Args:
            state: Current mission state with current_agent_index set
        
        Yields:
            MissionState updates during and after agent execution
        """
        # Store workflow agents in state for frontend display
        if not state.workflow_agents:
            state.workflow_agents = [a.__name__ for a in self.workflow]
        
        current_idx = state.current_agent_index
        
        # Check if workflow is complete
        if current_idx >= len(self.workflow):
            state.status = "COMPLETED"
            state.add_log("MissionControl: All agents completed")
            self._record_fair_use_costs(state)
            yield state
            return
        
        agent_class = self.workflow[current_idx]
        agent_name = agent_class.__name__
        
        state.status = "IN_PROGRESS"
        state.add_log(f"MissionControl: Step {current_idx + 1}/{len(self.workflow)} - Running {agent_name}...")
        yield state
        
        try:
            # Instantiate agent with services
            agent = agent_class(self.shop_id, services=self.services)
            
            # Inject regeneration feedback if present
            if state.regeneration_feedback:
                state.raw_input["_regeneration_feedback"] = state.regeneration_feedback
                state.add_log(f"MissionControl: Regenerating with feedback: {state.regeneration_feedback[:100]}...")
                state.regeneration_feedback = None  # Clear after use
            
            # Run the agent
            state = await agent.run(state)
            
            if state.status == "ERROR":
                logger.error(
                    "[MissionControl] Agent %s failed mission=%s shop=%s",
                    agent_name,
                    self.mission_id,
                    self.shop_id,
                )
                yield state
                return
            
            # Extract and store this agent's output
            agent_output = self._extract_agent_output(state, agent_name)
            state.agent_outputs[agent_name] = agent_output
            
            # Mark step complete - waiting for merchant decision
            state.status = "AWAITING_APPROVAL"
            state.add_log(f"MissionControl: {agent_name} completed - awaiting approval")
            
            logger.info(
                "[MissionControl] Step completed mission=%s agent=%s index=%d/%d",
                self.mission_id,
                agent_name,
                current_idx + 1,
                len(self.workflow),
            )
            
            yield state
            
        except Exception as e:
            logger.exception(
                "[MissionControl] Step failed mission=%s agent=%s",
                self.mission_id,
                agent_name,
            )
            state.set_error(f"{agent_name} failed: {str(e)}")
            yield state

    def _extract_agent_output(self, state: MissionState, agent_name: str) -> dict:
        """
        Extract the relevant output for a specific agent.
        
        This allows the frontend to display each agent's contribution clearly.
        
        Args:
            state: Current mission state
            agent_name: Name of the agent whose output to extract
        
        Returns:
            Dict containing the agent's specific output fields
        """
        if agent_name == "CopywriterAgent":
            return {
                "draft_content": state.draft_content,
                "draft_title": state.draft_title,
                "discovered_values": state.discovered_values,
            }
        elif agent_name == "SEOAgent":
            return {
                "seo_title": state.seo_title,
                "seo_description": state.seo_description,
                "seo_alt_text": state.seo_alt_text,
                "seo_insights": state.seo_insights,
                "ctr_check": state.ctr_check,
                "serp_insights": state.serp_insights,
            }
        elif agent_name == "MarketingAgent":
            return {
                "social_hooks": state.social_hooks,
                "seasonal_campaign": state.seasonal_campaign,
            }
        elif agent_name == "PriceScoutAgent":
            return {
                "pricing_analysis": state.pricing_analysis,
            }
        elif agent_name == "ComplianceAgent":
            # DISABLED - kept for reference
            return {
                "compliance_flags": state.compliance_flags,
            }
        else:
            return {}

    def advance_to_next_step(self, state: MissionState) -> MissionState:
        """
        Advance to the next agent in the workflow.
        
        Called when merchant clicks "Continue".
        
        Args:
            state: Current mission state
        
        Returns:
            Updated state with incremented index
        """
        state.current_agent_index += 1
        state.status = "PENDING"  # Ready for next step
        
        if state.current_agent_index >= len(self.workflow):
            state.status = "COMPLETED"
            state.add_log("MissionControl: All agents completed")
        else:
            next_agent = self.workflow[state.current_agent_index].__name__
            state.add_log(f"MissionControl: Advancing to {next_agent}")
        
        return state

    def skip_current_step(self, state: MissionState) -> MissionState:
        """
        Skip the current agent in the workflow.
        
        Called when merchant clicks "Skip".
        
        Args:
            state: Current mission state
        
        Returns:
            Updated state with skipped agent recorded
        """
        current_idx = state.current_agent_index
        if current_idx < len(self.workflow):
            skipped_agent = self.workflow[current_idx].__name__
            state.skipped_agents.append(skipped_agent)
            state.add_log(f"MissionControl: Skipped {skipped_agent}")
        
        state.current_agent_index += 1
        state.status = "PENDING"  # Ready for next step
        
        if state.current_agent_index >= len(self.workflow):
            state.status = "COMPLETED"
            state.add_log("MissionControl: All agents completed (some skipped)")
        
        return state

    def prepare_regeneration(self, state: MissionState, feedback: str = None) -> MissionState:
        """
        Prepare state for regenerating the current agent.
        
        Called when merchant clicks "Regenerate".
        
        Args:
            state: Current mission state
            feedback: Optional merchant feedback for regeneration
        
        Returns:
            Updated state ready for regeneration
        """
        current_idx = state.current_agent_index
        if current_idx < len(self.workflow):
            agent_name = self.workflow[current_idx].__name__
            state.regeneration_feedback = feedback
            state.status = "PENDING"  # Ready to re-run
            
            if feedback:
                state.add_log(f"MissionControl: Preparing to regenerate {agent_name} with feedback")
            else:
                state.add_log(f"MissionControl: Preparing to regenerate {agent_name}")
        
        return state

    def get_workflow_info(self) -> dict:
        """
        Get information about the current workflow configuration.
        
        Returns:
            Dict with workflow metadata
        """
        return {
            "mission_id": self.mission_id,
            "plan_tier": self.plan_tier,
            "shop_id": self.shop_id,
            "agents": [a.__name__ for a in self.workflow],
            "agent_count": len(self.workflow),
            "max_adversarial_iterations": self.MAX_ADVERSARIAL_ITERATIONS,
            "is_adhoc": self.requested_agents is not None,
            "requested_agents": self.requested_agents,
        }


# -----------------------------------------------------------------------------
# Convenience function for creating and running missions
# -----------------------------------------------------------------------------

async def run_mission(
    shop_id: str,
    product_data: dict,
    plan_tier: str = "Basic",
    db=None,
    target_locale: str = "en",
    requested_agents: Optional[List[str]] = None,
) -> AsyncGenerator[MissionState, None]:
    """
    Convenience function to create and run a mission.
    
    Args:
        shop_id: Shop domain identifier
        product_data: Product data dict (title, description, category, etc.)
        plan_tier: User's subscription tier
        db: Optional database session
        target_locale: Target language/locale
        requested_agents: Optional list of agent names for ad-hoc execution
                          e.g., ["CopywriterAgent"], ["MarketingAgent"]
    
    Yields:
        MissionState updates as agents complete
    """
    # Create initial state
    state = MissionState(
        product_id=product_data.get("product_id", "unknown"),
        shop_id=shop_id,
        plan_tier=plan_tier,
        raw_input=product_data,
        db=db,
        target_locale=target_locale,
    )
    
    # Create services and mission control
    services = ServiceRegistry.create_default()
    mission = MissionControl(
        plan_tier=plan_tier,
        shop_id=shop_id,
        services=services,
        requested_agents=requested_agents,
    )
    
    # Execute and yield updates
    async for updated_state in mission.execute(state):
        yield updated_state

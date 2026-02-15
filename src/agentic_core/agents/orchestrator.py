"""
MissionControl - Generic orchestrator for the multi-agent workflow.

This is the central coordinator that:
- Routes missions based on plan tier
- Supports ad-hoc agent execution (run specific agents only)
- Executes agents in sequence
- Handles gate logic for step-by-step approval
- Yields state updates for SSE streaming
- Records token usage via cost_recorder callback

Domain-specific agent maps and workflows are injected via class
attributes ``AGENT_MAP`` and ``WORKFLOWS``.  The Shopify ecommerce
layer provides a subclass that populates these with domain agents.
"""
from __future__ import annotations

from typing import Callable, List, Dict, Type, AsyncGenerator, Optional, Any
import uuid
from datetime import datetime

from .base import BaseAgent
from .state import GenericMissionState
from src.shared.logging.logger import get_logger

if TYPE_CHECKING := False:  # noqa: F841 - trick for forward-only import
    pass

# Use GenericMissionState as MissionState within this module
MissionState = GenericMissionState

# Type alias for cost recorder callback
CostRecorder = Callable[[str, dict, Any], None]  # (tenant_id, usage_dict, db)

logger = get_logger(__name__)


def register_agents(mapping: Dict[str, Type[BaseAgent]]) -> None:
    """
    Register domain-specific agents with MissionControl.

    Called at startup by the ecommerce layer to populate the agent map.
    Example::

        register_agents({
            "RewriterAgent": RewriterAgent,
            "SEOAgent": SEOAgent,
        })
    """
    MissionControl.AGENT_MAP.update(mapping)


class MissionControl:
    """
    Generic orchestrator for multi-agent workflows.

    Responsibilities:
    - Plan-based routing (tier → agent list)
    - Sequential agent execution
    - Gate logic (auto-proceed / await-approval)
    - State streaming for SSE
    - Cost recording via callback

    Subclasses (e.g. ShopifyMissionControl) override ``AGENT_MAP``,
    ``WORKFLOWS``, and ``_extract_agent_output`` to inject domain behaviour.
    """

    # ── Injectable class attributes ──────────────────────────────────────
    # Override in subclass or pass at construction time.
    AGENT_MAP: Dict[str, Type[BaseAgent]] = {}
    WORKFLOWS: Dict[str, List[Type[BaseAgent]]] = {}

    # Maximum adversarial iterations for compliance (0 = disabled)
    MAX_ADVERSARIAL_ITERATIONS = 0

    def __init__(
        self,
        plan_tier: str,
        shop_id: str,
        services: Any,
        requested_agents: Optional[List[str]] = None,
        mission_id: Optional[str] = None,
        workflow_config: Optional[List[Dict[str, Any]]] = None,
        cost_recorder: Optional[CostRecorder] = None,
        agent_map: Optional[Dict[str, Type[BaseAgent]]] = None,
        workflows: Optional[Dict[str, List[Type[BaseAgent]]]] = None,
    ):
        """
        Initialize MissionControl.

        Args:
            plan_tier: User's subscription tier (Free, Basic, Standard, Pro)
            shop_id: Shop domain identifier
            services: ServiceRegistry with injected services
            requested_agents: Optional list of agent names for ad-hoc execution
            mission_id: Optional mission ID from the database
            workflow_config: Optional merchant-defined pipeline config
            cost_recorder: Optional callback for recording accumulated LLM costs
            agent_map: Optional override for AGENT_MAP class attribute
            workflows: Optional override for WORKFLOWS class attribute
        """
        self.plan_tier = plan_tier
        self.shop_id = shop_id
        self.services = services
        self.requested_agents = requested_agents
        self.workflow_config = workflow_config or []
        self.mission_id = mission_id or uuid.uuid4().hex
        self._cost_recorder = cost_recorder
        # Pro tier gets autonomous publishing
        self.autonomous = (plan_tier == "Pro")

        # Allow per-instance override of class-level maps
        if agent_map is not None:
            self._agent_map = agent_map
        else:
            self._agent_map = self.__class__.AGENT_MAP

        if workflows is not None:
            self._workflows = workflows
        else:
            self._workflows = self.__class__.WORKFLOWS

        self.workflow = self._build_workflow()

    def _build_workflow(self) -> List[Type[BaseAgent]]:
        """
        Build the agent workflow based on workflow_config, requested_agents, or plan tier.

        Priority:
        1. workflow_config (Mission Architect) - highest priority
        2. requested_agents (ad-hoc mode)
        3. tier-based workflow (default)
        """
        # Mission Architect mode: build from workflow_config
        if self.workflow_config:
            workflow = []
            for step in self.workflow_config:
                agent_name = step.get("agent_name", "")
                if agent_name in self._agent_map:
                    workflow.append(self._agent_map[agent_name])
                else:
                    logger.warning(
                        "[MissionControl] Unknown agent in workflow_config: %s (skipped)",
                        agent_name,
                    )
            if workflow:
                logger.info(
                    "[MissionControl] Architect mode: running agents %s",
                    [a.__name__ for a in workflow],
                )
                return workflow
            logger.warning(
                "[MissionControl] No valid agents in workflow_config, falling back"
            )

        # Ad-hoc mode: use only the requested agents
        if self.requested_agents:
            workflow = []
            for agent_name in self.requested_agents:
                if agent_name in self._agent_map:
                    workflow.append(self._agent_map[agent_name])
                else:
                    logger.warning(
                        "[MissionControl] Unknown agent requested: %s (skipped)",
                        agent_name,
                    )
            if workflow:
                logger.info(
                    "[MissionControl] Ad-hoc mode: running agents %s",
                    [a.__name__ for a in workflow],
                )
                return workflow
            logger.warning(
                "[MissionControl] No valid agents in requested_agents, falling back to tier workflow"
            )

        # Default: tier-based workflow
        default_workflow = self._workflows.get(self.plan_tier, [])
        if not default_workflow:
            logger.warning(
                "[MissionControl] No workflow for tier=%s and no agents configured",
                self.plan_tier,
            )
        return default_workflow

    def _should_auto_proceed(self, state: MissionState, current_idx: int) -> bool:
        """Check whether the current step should auto-proceed (skip human gate)."""
        wf_config = state.workflow_config or self.workflow_config
        if not wf_config or current_idx >= len(wf_config):
            return False
        step_config = wf_config[current_idx]
        has_gate = step_config.get("has_gate", True)
        return not has_gate

    def _record_fair_use_costs(self, state: MissionState) -> None:
        """Record accumulated LLM costs via the cost_recorder callback."""
        try:
            accumulated = self.services.llm.get_accumulated_usage()

            if accumulated.total_tokens == 0:
                logger.debug("[MissionControl] No LLM usage to record for mission=%s", self.mission_id)
                return

            usage_dict = accumulated.to_dict()

            # Store usage info in state for auditing (attribute may not exist
            # on GenericMissionState — use setattr for safety)
            if hasattr(state, "accumulated_usage"):
                state.accumulated_usage = usage_dict

            # Fire cost recorder callback if provided
            if self._cost_recorder and state.db:
                try:
                    self._cost_recorder(self.shop_id, usage_dict, state.db)
                    logger.info(
                        "[MissionControl] Recorded fair_use costs mission=%s shop=%s "
                        "total_tokens=%d calls=%d models=%s",
                        self.mission_id,
                        self.shop_id,
                        accumulated.total_tokens,
                        accumulated.call_count,
                        accumulated.models_used,
                    )
                    state.add_log(
                        f"MissionControl: Recorded {accumulated.total_tokens} tokens "
                        f"({accumulated.call_count} LLM calls)"
                    )
                except Exception as e:
                    logger.warning(
                        "[MissionControl] Cost recorder callback failed mission=%s error=%s",
                        self.mission_id,
                        str(e),
                    )
            elif not self._cost_recorder:
                logger.debug(
                    "[MissionControl] No cost_recorder configured - usage stored in state only "
                    "mission=%s tokens=%d",
                    self.mission_id,
                    accumulated.total_tokens,
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
        """Execute the mission workflow, yielding state after each agent."""
        state.autonomous = self.autonomous
        state.status = "IN_PROGRESS"
        state.add_log(f"MissionControl: Starting {self.plan_tier} workflow")
        yield state

        try:
            for agent_class in self.workflow:
                agent = agent_class(self.shop_id, services=self.services)

                state.add_log(f"MissionControl: Running {agent.role_name}...")
                state = await agent.run(state)

                pass  # Placeholder for disabled compliance adversarial loop

                yield state

                if state.status == "ERROR":
                    logger.error(
                        "[MissionControl] Workflow halted on error mission=%s shop=%s",
                        self.mission_id,
                        self.shop_id,
                    )
                    return

            if state.status != "ERROR":
                if hasattr(state, "compliance_flags") and state.compliance_flags:
                    state.status = "COMPLIANCE_REVIEW"
                else:
                    state.status = "COMPLETED"

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
            self._record_fair_use_costs(state)
            yield state

    async def execute_single_agent(
        self,
        agent_class: Type[BaseAgent],
        state: MissionState,
    ) -> MissionState:
        """Execute a single agent (useful for testing or partial reruns)."""
        agent = agent_class(self.shop_id, services=self.services)
        return await agent.run(state)

    async def execute_single_step(
        self,
        state: MissionState,
    ) -> AsyncGenerator[MissionState, None]:
        """Execute only the current agent in the workflow (step-by-step mode)."""
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

        # ── Inject template_id for template steps ────────────────────────
        wf_config = state.workflow_config or self.workflow_config
        step_template_id = None
        if wf_config and current_idx < len(wf_config):
            step_template_id = wf_config[current_idx].get("template_id")

        if step_template_id:
            state.raw_input["template_id"] = step_template_id
            # Clear shared draft fields so previous step output doesn't leak
            if hasattr(state, "draft_content"):
                state.draft_content = None
            if hasattr(state, "draft_title"):
                state.draft_title = None
            state.add_log(
                f"MissionControl: Step {current_idx + 1}/{len(self.workflow)} - "
                f"Running {agent_name} with template '{step_template_id}'..."
            )
        else:
            state.raw_input.pop("template_id", None)
            state.add_log(
                f"MissionControl: Step {current_idx + 1}/{len(self.workflow)} - Running {agent_name}..."
            )

        # Propagate autonomous flag to state
        state.autonomous = self.autonomous

        state.status = "IN_PROGRESS"
        yield state

        try:
            agent = agent_class(self.shop_id, services=self.services)

            # Inject regeneration feedback if present
            if state.regeneration_feedback:
                state.raw_input["_regeneration_feedback"] = state.regeneration_feedback
                state.add_log(
                    f"MissionControl: Regenerating with feedback: {state.regeneration_feedback[:100]}..."
                )
                state.regeneration_feedback = None

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
            agent_output = self._extract_agent_output(state, agent_name, current_idx=current_idx)
            output_key = f"{agent_name}:{step_template_id}" if step_template_id else agent_name
            state.agent_outputs[output_key] = agent_output

            # Check gate logic: auto-proceed or wait for human
            if self._should_auto_proceed(state, current_idx):
                await self._on_step_approved(state, current_idx)
                state.current_agent_index += 1
                if state.current_agent_index >= len(self.workflow):
                    state.status = "COMPLETED"
                    state.add_log(
                        f"MissionControl: {agent_name} auto-approved (no gate) - all agents completed"
                    )
                    self._record_fair_use_costs(state)
                else:
                    state.status = "PENDING"
                    next_agent = self.workflow[state.current_agent_index].__name__
                    state.add_log(
                        f"MissionControl: {agent_name} auto-approved (no gate) - advancing to {next_agent}"
                    )

                logger.info(
                    "[MissionControl] Step auto-proceeded mission=%s agent=%s index=%d/%d",
                    self.mission_id,
                    agent_name,
                    current_idx + 1,
                    len(self.workflow),
                )
            else:
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

    def _extract_agent_output(
        self,
        state: MissionState,
        agent_name: str,
        current_idx: int | None = None,
    ) -> dict:
        """
        Extract the relevant output for a specific agent.

        The default implementation returns draft fields from state if they
        exist.  Domain subclasses (e.g. ShopifyMissionControl) override
        this to extract richer, domain-specific fields.
        """
        # ── Template step: return draft fields ───────────────────────────
        wf_config = state.workflow_config or self.workflow_config
        if current_idx is not None and wf_config and current_idx < len(wf_config):
            template_id = wf_config[current_idx].get("template_id")
            if template_id:
                return {
                    "template_id": template_id,
                    "draft_content": getattr(state, "draft_content", None),
                    "draft_title": getattr(state, "draft_title", None),
                }

        # ── Generic: return all state as dict ────────────────────────────
        return {
            "draft_content": getattr(state, "draft_content", None),
            "draft_title": getattr(state, "draft_title", None),
        }

    async def _on_step_approved(self, state: MissionState, step_idx: int) -> None:
        """After a step is approved, call its agent's publish hook."""
        if not state.autonomous:
            return

        agent_class = self.workflow[step_idx]
        agent = agent_class(self.shop_id, services=self.services)

        wf_config = state.workflow_config or self.workflow_config
        template_id = None
        if wf_config and step_idx < len(wf_config):
            template_id = wf_config[step_idx].get("template_id")

        # ── Restore draft_content for the approved step ──────────────────
        output_key = (
            f"{agent_class.__name__}:{template_id}"
            if template_id
            else agent_class.__name__
        )
        step_output = state.agent_outputs.get(output_key, {})
        saved_content = getattr(state, "draft_content", None)
        saved_title = getattr(state, "draft_title", None)
        if step_output:
            if hasattr(state, "draft_content"):
                state.draft_content = step_output.get("draft_content", saved_content)
            if hasattr(state, "draft_title"):
                state.draft_title = step_output.get("draft_title", saved_title)

        is_published, error = await agent._maybe_publish(state, template_id)

        # Restore previous draft_content so later steps are not affected
        if step_output:
            if hasattr(state, "draft_content"):
                state.draft_content = saved_content
            if hasattr(state, "draft_title"):
                state.draft_title = saved_title

        # Inject is_published into agent_outputs for this step
        output_key = (
            f"{agent_class.__name__}:{template_id}"
            if template_id
            else agent_class.__name__
        )
        if output_key in state.agent_outputs:
            state.agent_outputs[output_key]["is_published"] = is_published
            if error:
                state.agent_outputs[output_key]["publish_error"] = error

    async def advance_to_next_step(self, state: MissionState) -> MissionState:
        """Advance to the next agent after approval."""
        approved_idx = state.current_agent_index
        await self._on_step_approved(state, approved_idx)

        state.current_agent_index += 1
        state.status = "PENDING"

        if state.current_agent_index >= len(self.workflow):
            state.status = "COMPLETED"
            state.add_log("MissionControl: All agents completed")
        else:
            next_agent = self.workflow[state.current_agent_index].__name__
            state.add_log(f"MissionControl: Advancing to {next_agent}")

        return state

    def skip_current_step(self, state: MissionState) -> MissionState:
        """Skip the current agent in the workflow."""
        current_idx = state.current_agent_index
        if current_idx < len(self.workflow):
            skipped_agent = self.workflow[current_idx].__name__
            state.skipped_agents.append(skipped_agent)
            state.add_log(f"MissionControl: Skipped {skipped_agent}")

        state.current_agent_index += 1
        state.status = "PENDING"

        if state.current_agent_index >= len(self.workflow):
            state.status = "COMPLETED"
            state.add_log("MissionControl: All agents completed (some skipped)")

        return state

    def prepare_regeneration(self, state: MissionState, feedback: str = None) -> MissionState:
        """Prepare state for regenerating the current agent."""
        current_idx = state.current_agent_index
        if current_idx < len(self.workflow):
            agent_name = self.workflow[current_idx].__name__
            state.regeneration_feedback = feedback
            state.status = "PENDING"

            if feedback:
                state.add_log(f"MissionControl: Preparing to regenerate {agent_name} with feedback")
            else:
                state.add_log(f"MissionControl: Preparing to regenerate {agent_name}")

        return state

    def get_workflow_info(self) -> dict:
        """Get information about the current workflow configuration."""
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

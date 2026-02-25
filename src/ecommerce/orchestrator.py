"""
Shopify-configured MissionControl (shim).

Canonical generic orchestrator: src/agentic_core/agents/orchestrator.py

This module:
1. Re-exports MissionControl with Shopify-specific AGENT_MAP and WORKFLOWS
2. Provides domain-specific _extract_agent_output for the Shopify frontend
3. Defines run_mission convenience function with Shopify wiring
"""
from __future__ import annotations

from typing import Callable, List, Dict, Type, AsyncGenerator, Optional, Any

from src.agentic_core.agents.orchestrator import (
    MissionControl as _GenericMissionControl,
    CostRecorder,
)
from src.agentic_core.agents.base import BaseAgent

from .state import MissionState
from .agents.rewriter import RewriterAgent
from .agents.seo import SEOAgent
from .agents.marketing import MarketingAgent
from .agents.price_scout import PriceScoutAgent
from .agents.compliance import ComplianceAgent  # Kept for reference but disabled
from .agents.visual import VisualAgent
from .agents.image_refinement import ImageRefinementAgent
from .agents.visual_marketing import VisualMarketingAgent
from .agents.content_hero import ContentHeroAgent
from src.agentic_core.registry import ServiceRegistry
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

# Agent name to class mapping for ad-hoc agent selection
AGENT_MAP: Dict[str, Type[BaseAgent]] = {
    "RewriterAgent": RewriterAgent,
    "CopywriterAgent": RewriterAgent,  # Backward compat alias
    "SEOAgent": SEOAgent,
    "MarketingAgent": MarketingAgent,
    "PriceScoutAgent": PriceScoutAgent,
    "ImageRefinementAgent": ImageRefinementAgent,
    "VisualMarketingAgent": VisualMarketingAgent,
    "VisualAgent": VisualAgent,  # backward compat for existing missions
    "ContentHeroAgent": ContentHeroAgent,
    # "ComplianceAgent": ComplianceAgent,  # DISABLED
}


class MissionControl(_GenericMissionControl):
    """
    Shopify-configured MissionControl that injects domain-specific
    agent map, workflows, and output extraction.
    """

    # Shopify-specific agent map and workflows
    AGENT_MAP = AGENT_MAP
    WORKFLOWS = {
        "Free": [RewriterAgent, ImageRefinementAgent, SEOAgent, PriceScoutAgent, MarketingAgent, VisualMarketingAgent],
        "Basic": [RewriterAgent, MarketingAgent],
        "Standard": [RewriterAgent, SEOAgent, MarketingAgent, PriceScoutAgent],
        "Pro": [RewriterAgent, ImageRefinementAgent, SEOAgent, PriceScoutAgent, MarketingAgent, VisualMarketingAgent],
    }

    # Default fallback workflow for unknown tiers
    DEFAULT_WORKFLOW = [RewriterAgent]

    def _build_workflow(self) -> List[Type[BaseAgent]]:
        """Override to provide fallback to DEFAULT_WORKFLOW for unknown tiers."""
        result = super()._build_workflow()
        if not result:
            return list(self.DEFAULT_WORKFLOW)
        return result

    def _extract_agent_output(
        self,
        state: MissionState,
        agent_name: str,
        current_idx: int | None = None,
    ) -> dict:
        """
        Extract the relevant output for a specific agent.

        Shopify-specific: maps agent names to their domain fields.
        """
        # ── Template step: always return draft_content ───────────────────
        wf_config = state.workflow_config or self.workflow_config
        if current_idx is not None and wf_config and current_idx < len(wf_config):
            template_id = wf_config[current_idx].get("template_id")
            if template_id:
                return {
                    "template_id": template_id,
                    "draft_content": state.draft_content,
                    "draft_title": state.draft_title,
                }

        # ── Regular agent step ───────────────────────────────────────────
        if agent_name in ("RewriterAgent", "CopywriterAgent"):
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
            return {
                "compliance_flags": state.compliance_flags,
            }
        elif agent_name == "VisualAgent":
            return {
                "visual_assets": state.visual_assets,
                "visual_progress": state.visual_progress,
            }
        elif agent_name == "ImageRefinementAgent":
            return {
                "visual_assets": state.visual_assets,
                "visual_progress": state.visual_progress,
            }
        elif agent_name == "VisualMarketingAgent":
            return {
                "visual_assets": state.visual_assets,
                "visual_progress": state.visual_progress,
            }
        elif agent_name == "ContentHeroAgent":
            return {
                "content_hero_assets": state.content_hero_assets,
            }
        else:
            return {}

    async def _handle_adversarial_loop(
        self,
        state: MissionState,
    ) -> MissionState:
        """
        Handle adversarial loop: Compliance rejection → Rewriter regeneration.
        DISABLED (MAX_ADVERSARIAL_ITERATIONS = 0).
        """
        iteration = 0

        while (
            hasattr(state, "compliance_flags")
            and state.compliance_flags
            and iteration < self.MAX_ADVERSARIAL_ITERATIONS
        ):
            iteration += 1
            state.add_log(
                f"MissionControl: Adversarial iteration {iteration} - "
                f"regenerating for compliance ({len(state.compliance_flags)} flags)"
            )

            compliance_feedback = "\n".join([
                f"- {flag}" for flag in state.compliance_flags
            ])
            state.raw_input["compliance_feedback"] = compliance_feedback
            state.raw_input["_regeneration_attempt"] = iteration

            state.compliance_flags = []

            rewriter = RewriterAgent(self.shop_id, services=self.services)
            state = await rewriter.run(state)

            if state.status == "ERROR":
                break

            compliance = ComplianceAgent(self.shop_id, services=self.services)
            state = await compliance.run(state)

        if iteration > 0:
            state.add_log(
                f"MissionControl: Adversarial loop completed after {iteration} iterations"
            )
            if hasattr(state, "compliance_flags") and state.compliance_flags:
                logger.warning(
                    "[MissionControl] Compliance issues remain after %d iterations mission=%s",
                    iteration,
                    self.mission_id,
                )

        return state


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
    services = ServiceRegistry.create_default(db=db, shop_domain=shop_id)

    # Build the cost recorder callback
    cost_recorder = _build_cost_recorder()

    mission = MissionControl(
        plan_tier=plan_tier,
        shop_id=shop_id,
        services=services,
        requested_agents=requested_agents,
        cost_recorder=cost_recorder,
    )

    async for updated_state in mission.execute(state):
        yield updated_state


def _build_cost_recorder() -> Optional[CostRecorder]:
    """Build a cost recorder callback that routes to fair_use_service."""
    try:
        from src.ecommerce.services.fair_use_service import record_cost_from_usage

        def _recorder(tenant_id: str, usage_dict: dict, db: Any) -> None:
            models_used = usage_dict.get("models_used", [])
            model_used = "gpt-4o"
            if models_used:
                model_used = "gpt-4o" if "gpt-4o" in models_used else models_used[0]

            cost_usage = {
                "prompt_tokens": usage_dict.get("prompt_tokens", 0),
                "completion_tokens": usage_dict.get("completion_tokens", 0),
                "reasoning_tokens": usage_dict.get("reasoning_tokens", 0),
                "total_tokens": usage_dict.get("total_tokens", 0),
            }
            record_cost_from_usage(
                db=db,
                shop_domain=tenant_id,
                usage=cost_usage,
                model_used=model_used,
            )

        return _recorder
    except ImportError:
        return None

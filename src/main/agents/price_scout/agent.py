"""
PriceScoutAgent - Analyzes competitor pricing using SERP data.

This agent gathers competitor pricing information from search results
and provides pricing recommendations using structured LLM analysis.
"""

from typing import List, Tuple

from ..base import BaseAgent
from ..state import MissionState
from ..context import AgentContext, AgentPlan, AgentAction
from .prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT_TEMPLATE, NO_COMPETITORS_MESSAGE
from .schemas import PricingAnalysis
from src.main.logging.logger import get_logger

logger = get_logger(__name__)


class PriceScoutAgent(BaseAgent):
    """
    Agent for competitor pricing analysis.
    
    Uses:
    - SERP API for competitor data (Perception) - NOT an LLM call
    - Deterministic planning (Reasoning)
    - Structured LLM for analysis (Action) - SINGLE LLM CALL
    
    This agent helps merchants understand their competitive position
    and make data-driven pricing decisions.
    """
    
    role_name = "PriceScout"
    default_tool = "llm.generate_structured"
    
    # NOTE: requires_llm_reasoning = False (default)

    # -------------------------------------------------------------------------
    # PERCEPTION: Gather competitor data via SERP (NO LLM call)
    # -------------------------------------------------------------------------
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """
        Gather competitor pricing data via SERP API.
        
        This uses the SerpService to fetch competitor product listings,
        which are then analyzed in the Action phase.
        """
        product_name = context.get_product_title()
        category = context.get_category()
        
        try:
            # SERP API call (not LLM)
            competitors = await self.services.serp.get_competitor_prices(
                product_name=product_name,
                category=category,
            )
            
            context.external_data["competitors"] = competitors
            context.external_data["competitor_count"] = len(competitors)
            
            if competitors:
                logger.info(
                    "[PriceScout] Found %d competitors for product=%s",
                    len(competitors),
                    product_name[:30],
                )
            else:
                logger.info(
                    "[PriceScout] No competitors found for product=%s",
                    product_name[:30],
                )
                
        except Exception as e:
            logger.warning(
                "[PriceScout] Failed to fetch competitors shop=%s err=%s",
                self.shop_id,
                e,
            )
            context.external_data["competitors"] = []
            context.external_data["competitor_count"] = 0
        
        return context

    # NOTE: Uses default deterministic plan - NO LLM call in reasoning

    # -------------------------------------------------------------------------
    # ACTION: Analyze pricing (SINGLE LLM CALL)
    # -------------------------------------------------------------------------
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Analyze competitor pricing using structured LLM output.
        
        This is the ONLY LLM call for this agent.
        """
        actions = []
        
        competitors = context.external_data.get("competitors", [])
        product_name = context.get_product_title()
        category = context.get_category()
        
        # If no competitor data, return early with empty analysis
        if not competitors:
            state.pricing_analysis = {
                "competitor_avg_price": 0.0,
                "recommended_price": 0.0,
                "price_position": "unknown",
                "confidence": 0.0,
                "reasoning": NO_COMPETITORS_MESSAGE,
                "competitor_count": 0,
            }
            actions.append(
                AgentAction.success_action(
                    tool_name="skip",
                    output="No competitors to analyze",
                    input_params={},
                )
            )
            return actions, state
        
        # Build analysis prompt
        prompt = self._build_analysis_prompt(product_name, category, competitors)
        
        try:
            # === THE ONLY LLM CALL FOR THIS AGENT ===
            analysis = await self.services.llm.generate_structured(
                prompt=prompt,
                response_format=PricingAnalysis,
                system_prompt=SYSTEM_PROMPT,
                model="gpt-4o-mini",  # Cheaper model for structured extraction
                temperature=0.0,  # Deterministic
            )
            
            # Convert Pydantic model to dict for state storage
            analysis_dict = analysis.model_dump()
            analysis_dict["competitor_count"] = len(competitors)
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_structured",
                    output=analysis_dict,
                    input_params={"response_format": "PricingAnalysis"},
                )
            )
            
            state.pricing_analysis = analysis_dict
            
            logger.info(
                "[PriceScout] Analysis complete product=%s position=%s confidence=%.2f",
                product_name[:30],
                analysis.price_position,
                analysis.confidence,
            )
            
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_structured",
                    error=str(e),
                    input_params={"response_format": "PricingAnalysis"},
                )
            )
            logger.error(
                "[PriceScout] Analysis failed product=%s err=%s",
                product_name[:30],
                e,
            )
            # Don't fail the whole mission, just log
            state.pricing_analysis = None
        
        return actions, state

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------
    def _build_analysis_prompt(
        self,
        product_name: str,
        category: str,
        competitors: List[dict],
    ) -> str:
        """Build prompt for pricing analysis."""
        competitor_text = "\n".join([
            f"- {c.get('title', 'Unknown')}: {c.get('snippet', '')}"
            for c in competitors[:5]  # Limit to top 5
        ])
        
        return ANALYSIS_PROMPT_TEMPLATE.format(
            product_name=product_name,
            category=category,
            competitor_text=competitor_text,
        )

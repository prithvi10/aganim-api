"""
PriceScoutAgent - Smart Price Discovery using Google Shopping and Semantic Filtering.

This agent gathers competitor pricing from Google Shopping API, filters irrelevant
items using LLM semantic analysis, and provides data-driven pricing recommendations.
"""

import json
import statistics
from typing import List, Optional, Tuple, Dict, Any

from src.agentic_core.agents.base import BaseAgent
from src.ecommerce.state import ShopifyMissionState as MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction
from .prompts import (
    SYSTEM_PROMPT,
    ANALYSIS_PROMPT_TEMPLATE,
    NO_COMPETITORS_MESSAGE,
    FILTER_COMPETITORS_PROMPT,
    ANALYSIS_WITH_METRICS_PROMPT,
)
from .schemas import PricingAnalysis, FilteredCompetitorsResponse, MarketAnalysis
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)


class PriceScoutAgent(BaseAgent):
    """
    Agent for Smart Price Discovery.
    
    Architecture (2 LLM calls):
    1. PERCEPTION: Fetch 20 competitors from Google Shopping API (no LLM)
    2. FILTERING: Semantic filter to keep only true comparables (LLM call 1)
    3. METRICS: Calculate min/max/avg/median from filtered list (no LLM)
    4. ANALYSIS: Generate pricing recommendation (LLM call 2)
    
    This agent helps merchants understand their competitive position
    and make data-driven pricing decisions with curated market data.
    """
    
    role_name = "PriceScout"
    default_tool = "llm.generate_structured"
    
    # NOTE: requires_llm_reasoning = False (default)

    # ── Autonomous Publish: override _maybe_publish with guardrails ───
    async def _maybe_publish(
        self,
        state: "MissionState",
        template_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Publish recommended price to Shopify, validating against price_guardrails.
        
        Guardrails format in Shop model:
            {"min_price": 0, "max_price": 9999}
        """
        if not state.autonomous:
            return False, None

        analysis = state.pricing_analysis or {}
        recommended_price = analysis.get("recommended_price")
        if not recommended_price or recommended_price <= 0:
            return False, "no_recommended_price"

        # Load credentials and guardrails via publish adapter
        publish_adapter = getattr(self.services, "publish_adapter", None)
        if publish_adapter is None:
            logger.debug("[PriceScout] No publish_adapter configured – skipping publish")
            return False, None

        creds = {}
        if state.db:
            creds = await publish_adapter.get_credentials(state.db, state.shop_id)

        if not creds.get("access_token"):
            state.add_log("PriceScout: Publish skipped – missing shop credentials")
            return False, "missing_credentials"

        # Validate against guardrails
        guardrails = creds.get("price_guardrails") or {}
        min_price = guardrails.get("min_price", 0)
        max_price = guardrails.get("max_price", float("inf"))

        if not (min_price <= recommended_price <= max_price):
            state.add_log(
                f"PriceScout: ❌ Price {recommended_price} outside guardrails "
                f"[{min_price} - {max_price}] – not published"
            )
            return False, "price_outside_guardrails"

        # Get variant_id from raw_input or analysis
        variant_id = (
            state.raw_input.get("variant_id")
            or analysis.get("variant_id")
        )
        if not variant_id:
            state.add_log("PriceScout: Publish skipped – no variant_id")
            return False, "missing_variant_id"

        try:
            await publish_adapter.update_variant_price(
                shop_domain=state.shop_id,
                access_token=creds["access_token"],
                variant_id=variant_id,
                price=str(recommended_price),
            )
            state.add_log(
                f"PriceScout: ✅ Variant {variant_id} price → {recommended_price}"
            )
            logger.info(
                "[PriceScout] Published price=%s variant=%s shop=%s",
                recommended_price,
                variant_id,
                state.shop_id,
            )
            return True, None
        except Exception as e:
            error_msg = str(e)
            state.add_log(f"PriceScout: ❌ Publish failed: {error_msg}")
            logger.error(
                "[PriceScout] Publish failed variant=%s shop=%s err=%s",
                variant_id,
                state.shop_id,
                error_msg,
            )
            return False, error_msg

    # -------------------------------------------------------------------------
    # PERCEPTION: Gather competitor data via Google Shopping (NO LLM call)
    # -------------------------------------------------------------------------
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """
        Gather competitor pricing data via Google Shopping API.
        
        Fetches 20 results with structured price data.
        Items without valid extracted_price are filtered at service level.
        """
        product_name = context.get_product_title()
        category = context.get_category()
        
        try:
            from src.ecommerce.config.shopify_config import LOCALE_TO_SERP_PARAMS
            target_locale = state.target_locale or state.raw_input.get("target_locale", "en")
            serp_params = LOCALE_TO_SERP_PARAMS.get(target_locale, {})

            competitors = await self.services.serp.get_competitor_prices(
                product_name=product_name,
                category=category,
                num_results=20,
                location=serp_params.get("location"),
                gl=serp_params.get("gl"),
                hl=serp_params.get("hl"),
            )
            
            context.external_data["raw_competitors"] = competitors
            context.external_data["raw_competitor_count"] = len(competitors)
            
            if competitors:
                logger.info(
                    "[PriceScout] Fetched %d shopping results for product=%s",
                    len(competitors),
                    product_name[:30],
                )
            else:
                logger.info(
                    "[PriceScout] No shopping results found for product=%s",
                    product_name[:30],
                )
                
        except Exception as e:
            logger.warning(
                "[PriceScout] Failed to fetch shopping results shop=%s err=%s",
                self.shop_id,
                e,
            )
            context.external_data["raw_competitors"] = []
            context.external_data["raw_competitor_count"] = 0
        
        return context

    # NOTE: Uses default deterministic plan - NO LLM call in reasoning

    # -------------------------------------------------------------------------
    # ACTION: Filter + Analyze (2 LLM CALLS)
    # -------------------------------------------------------------------------
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Smart Price Discovery flow:
        1. Get raw competitors from perception
        2. Semantic filtering (LLM call 1)
        3. Calculate market metrics from filtered list
        4. Generate pricing recommendation (LLM call 2)
        """
        actions = []
        
        raw_competitors = context.external_data.get("raw_competitors", [])
        product_name = context.get_product_title()
        category = context.get_category()
        description = context.get_product_description() or product_name
        
        # If no competitor data, return early with empty analysis
        if not raw_competitors:
            state.pricing_analysis = {
                "competitor_avg_price": 0.0,
                "recommended_price": 0.0,
                "price_position": "unknown",
                "confidence": 0.0,
                "reasoning": NO_COMPETITORS_MESSAGE,
                "competitor_count": 0,
                "valid_competitors": [],
                "market_analysis": None,
                "filter_reasoning": "No competitors fetched from Google Shopping.",
            }
            actions.append(
                AgentAction.success_action(
                    tool_name="skip",
                    output="No competitors to analyze",
                    input_params={},
                )
            )
            return actions, state
        
        # === STEP 1: Semantic Filtering (LLM Call 1) ===
        valid_competitors, filter_reasoning = await self._filter_competitors(
            product_title=product_name,
            product_description=description,
            category=category,
            raw_competitors=raw_competitors,
        )
        
        actions.append(
            AgentAction.success_action(
                tool_name="llm.generate_structured",
                output={
                    "step": "semantic_filtering",
                    "raw_count": len(raw_competitors),
                    "filtered_count": len(valid_competitors),
                },
                input_params={"response_format": "FilteredCompetitorsResponse"},
            )
        )
        
        # If all competitors were filtered out, use raw data with low confidence
        if not valid_competitors:
            logger.warning(
                "[PriceScout] All competitors filtered out, using raw data for product=%s",
                product_name[:30],
            )
            valid_competitors = raw_competitors[:5]  # Use top 5 raw results
            filter_reasoning += " (Fallback: using top raw results as filter was too aggressive)"
        
        # === STEP 2: Calculate Market Metrics (No LLM) ===
        market_analysis = self._calculate_market_metrics(valid_competitors)
        
        # === STEP 3: Generate Pricing Recommendation (LLM Call 2) ===
        analysis_dict = await self._generate_pricing_recommendation(
            product_name=product_name,
            product_description=description,
            category=category,
            valid_competitors=valid_competitors,
            market_analysis=market_analysis,
            filter_reasoning=filter_reasoning,
        )
        
        actions.append(
            AgentAction.success_action(
                tool_name="llm.generate_structured",
                output={
                    "step": "pricing_analysis",
                    "recommended_price": analysis_dict.get("recommended_price"),
                    "price_position": analysis_dict.get("price_position"),
                    "confidence": analysis_dict.get("confidence"),
                },
                input_params={"response_format": "PricingAnalysis"},
            )
        )
        
        # Store enriched analysis in state
        state.pricing_analysis = {
            **analysis_dict,
            "valid_competitors": valid_competitors,
            "market_analysis": market_analysis,
            "filter_reasoning": filter_reasoning,
            "raw_competitor_count": len(raw_competitors),
        }
        
        logger.info(
            "[PriceScout] Analysis complete product=%s filtered=%d/%d position=%s confidence=%.2f",
            product_name[:30],
            len(valid_competitors),
            len(raw_competitors),
            analysis_dict.get("price_position"),
            analysis_dict.get("confidence", 0),
        )
        
        return actions, state

    # -------------------------------------------------------------------------
    # Semantic Filtering (LLM Call 1)
    # -------------------------------------------------------------------------
    async def _filter_competitors(
        self,
        product_title: str,
        product_description: str,
        category: str,
        raw_competitors: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        Use LLM to filter irrelevant competitors based on semantic analysis.
        
        Returns:
            Tuple of (valid_competitors list, reasoning string)
        """
        # Format competitors as JSON for the prompt
        competitors_for_prompt = [
            {
                "index": i,
                "title": c.get("title", ""),
                "price": c.get("price", ""),
                "extracted_price": c.get("extracted_price"),
                "source": c.get("source", ""),
                "link": c.get("link", ""),
            }
            for i, c in enumerate(raw_competitors)
        ]
        
        prompt = FILTER_COMPETITORS_PROMPT.format(
            product_title=product_title,
            product_description=product_description,
            category=category,
            competitors_json=json.dumps(competitors_for_prompt, indent=2),
        )
        
        try:
            filter_response = await self.services.llm.generate_structured(
                prompt=prompt,
                response_format=FilteredCompetitorsResponse,
                system_prompt="You are a Market Analyst specializing in e-commerce product comparison.",
                model="gpt-4o-mini",  # Fast and cheap for filtering
                temperature=0.0,  # Deterministic
            )
            
            valid_indices = set(filter_response.valid_competitor_indices)
            valid_competitors = [
                c for i, c in enumerate(raw_competitors)
                if i in valid_indices
            ]
            
            logger.info(
                "[PriceScout] Semantic filter: %d/%d competitors kept",
                len(valid_competitors),
                len(raw_competitors),
            )
            
            return valid_competitors, filter_response.reasoning
            
        except Exception as e:
            logger.warning(
                "[PriceScout] Semantic filtering failed, using all competitors: %s",
                e,
            )
            # Fallback: return all competitors if filtering fails
            return raw_competitors, f"Filtering skipped due to error: {str(e)}"

    # -------------------------------------------------------------------------
    # Market Metrics Calculation (No LLM)
    # -------------------------------------------------------------------------
    def _calculate_market_metrics(
        self,
        competitors: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Calculate market statistics from filtered competitors.
        
        Returns dict with min_price, max_price, average_price, median_price, competitor_count.
        """
        prices = [
            c["extracted_price"]
            for c in competitors
            if c.get("extracted_price") and c["extracted_price"] > 0
        ]
        
        if not prices:
            return {
                "min_price": 0.0,
                "max_price": 0.0,
                "average_price": 0.0,
                "median_price": 0.0,
                "competitor_count": 0,
            }
        
        return {
            "min_price": min(prices),
            "max_price": max(prices),
            "average_price": sum(prices) / len(prices),
            "median_price": statistics.median(prices),
            "competitor_count": len(prices),
        }

    # -------------------------------------------------------------------------
    # Pricing Recommendation (LLM Call 2)
    # -------------------------------------------------------------------------
    async def _generate_pricing_recommendation(
        self,
        product_name: str,
        product_description: str,
        category: str,
        valid_competitors: List[Dict[str, Any]],
        market_analysis: Dict[str, Any],
        filter_reasoning: str,
    ) -> Dict[str, Any]:
        """
        Generate final pricing recommendation using filtered data and metrics.
        """
        # Format filtered competitors for prompt
        competitor_text = "\n".join([
            f"- {c.get('title', 'Unknown')} ({c.get('source', 'Unknown')}): {c.get('price', 'N/A')}"
            for c in valid_competitors[:10]  # Show top 10
        ])
        
        prompt = ANALYSIS_WITH_METRICS_PROMPT.format(
            product_name=product_name,
            product_description=product_description,
            category=category,
            competitor_count=market_analysis.get("competitor_count", 0),
            min_price=market_analysis.get("min_price", 0),
            max_price=market_analysis.get("max_price", 0),
            average_price=market_analysis.get("average_price", 0),
            median_price=market_analysis.get("median_price", 0),
            competitor_text=competitor_text,
            filter_reasoning=filter_reasoning,
        )
        
        try:
            analysis = await self.services.llm.generate_structured(
                prompt=prompt,
                response_format=PricingAnalysis,
                system_prompt=SYSTEM_PROMPT,
                model="gpt-4o-mini",
                temperature=0.0,
            )
            
            analysis_dict = analysis.model_dump()
            # Use average from our calculated metrics
            analysis_dict["competitor_avg_price"] = market_analysis.get("average_price", 0)
            analysis_dict["competitor_count"] = market_analysis.get("competitor_count", 0)
            
            return analysis_dict
            
        except Exception as e:
            logger.error(
                "[PriceScout] Pricing recommendation failed: %s",
                e,
            )
            # Return fallback with calculated metrics
            return {
                "competitor_avg_price": market_analysis.get("average_price", 0),
                "recommended_price": market_analysis.get("median_price", 0),
                "price_position": "competitive",
                "confidence": 0.3,
                "reasoning": f"Analysis failed, using median price as fallback. Error: {str(e)}",
                "competitor_count": market_analysis.get("competitor_count", 0),
            }

    # -------------------------------------------------------------------------
    # Legacy Helper (backward compatibility)
    # -------------------------------------------------------------------------
    def _build_analysis_prompt(
        self,
        product_name: str,
        category: str,
        competitors: List[dict],
    ) -> str:
        """Build legacy prompt for pricing analysis (backward compatibility)."""
        competitor_text = "\n".join([
            f"- {c.get('title', 'Unknown')}: {c.get('snippet', c.get('price', ''))}"
            for c in competitors[:5]
        ])
        
        return ANALYSIS_PROMPT_TEMPLATE.format(
            product_name=product_name,
            category=category,
            competitor_text=competitor_text,
        )

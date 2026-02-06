"""
SEOAgent - Handles all SEO-related functionality.

This agent handles:
- SERP competitor analysis (Perception - NO LLM)
- SEO title/description/alt-text generation (Action - 1 LLM call)
- CTR/PST formula validation (Action - NO LLM, deterministic)
"""

import re
from typing import List, Tuple, Dict, Any

from ..base import BaseAgent
from ..state import MissionState
from ..context import AgentContext, AgentPlan, AgentAction
from .prompts import (
    SEO_SYSTEM_PROMPT,
    SEO_USER_PROMPT_TEMPLATE,
    PST_PAIN_PATTERNS,
    PST_SOLUTION_PATTERNS,
    PST_TRUST_PATTERNS,
)
from .schemas import SEOOutput, SEOInsights, CTRCheck, SerpCompetitor
from src.main.logging.logger import get_logger

logger = get_logger(__name__)


class SEOAgent(BaseAgent):
    """
    Agent for SEO optimization and CTR checking.
    
    Responsibilities:
    - SERP competitor fetch (Perception - NO LLM)
    - SEO title/description/alt-text generation (Action - 1 LLM call)
    - CTR/PST formula validation (Action - NO LLM, deterministic)
    
    LLM Calls: 1 (for SEO generation)
    """
    
    role_name = "SEO"
    default_tool = "llm.generate_text"

    # -------------------------------------------------------------------------
    # PERCEPTION: Gather SERP competitor data (NO LLM call)
    # -------------------------------------------------------------------------
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """
        Gather competitor data from SERP.
        
        Fetches top 3 Google results for the product to inform
        SEO generation with competitive insights.
        """
        product_title = context.get_product_title()
        category = context.get_category()
        
        # Build search query
        search_query = f"{product_title} {category}".strip()
        
        if search_query:
            try:
                # Fetch top 3 competitors from Google
                serp_results = await self.services.serp.search(
                    query=search_query,
                    num_results=3,
                )
                
                # Store in context for SEO generation
                context.serp_results = [
                    {
                        "title": r.title,
                        "snippet": r.snippet,
                        "link": r.link,
                        "position": r.position,
                    }
                    for r in serp_results
                ]
                
                if serp_results:
                    logger.info(
                        "[SEO] Loaded %d SERP results for query=%s",
                        len(serp_results),
                        search_query[:50],
                    )
            except Exception as e:
                logger.warning(
                    "[SEO] SERP fetch failed query=%s err=%s",
                    search_query[:50],
                    e,
                )
                context.serp_results = []
        else:
            context.serp_results = []
        
        return context

    # -------------------------------------------------------------------------
    # ACTION: Generate SEO + CTR check
    # -------------------------------------------------------------------------
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Execute SEO actions:
        1. Generate SEO metadata (1 LLM call)
        2. Run CTR/PST check (deterministic)
        """
        actions = []
        
        # Get product data
        title = context.get_product_title()
        description = state.draft_content or context.get_product_description()
        category = context.get_category()
        target_locale = state.target_locale or state.raw_input.get("target_locale", "en")
        
        # Store SERP insights in state
        serp_results = getattr(context, 'serp_results', [])
        state.serp_insights = serp_results
        
        # -----------------------------------------------------------------
        # Step 1: Generate SEO metadata (1 LLM call)
        # -----------------------------------------------------------------
        try:
            seo_result = await self._generate_seo(
                title=title,
                description=description,
                category=category,
                target_locale=target_locale,
                serp_results=serp_results,
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_text",
                    output="SEO metadata generated",
                    input_params={"step": "seo_generation"},
                )
            )
            
            # Update state with SEO fields
            state.seo_title = seo_result.get("seo_title", "")
            state.seo_description = seo_result.get("seo_description", "")
            state.seo_alt_text = seo_result.get("seo_alt_text", "")
            state.seo_insights = seo_result.get("seo_insights", {})
            
            logger.info(
                "[SEO] SEO generated for product=%s shop=%s",
                state.product_id,
                self.shop_id,
            )
            
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"step": "seo_generation"},
                )
            )
            logger.error("[SEO] SEO generation failed: %s", e)
        
        # -----------------------------------------------------------------
        # Step 2: Run CTR/PST check (deterministic - NO LLM)
        # -----------------------------------------------------------------
        try:
            ctr_result = self._check_ctr_pst(
                description=description,
                seo_description=state.seo_description or "",
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="deterministic.ctr_check",
                    output=f"CTR score: {ctr_result['score']:.2f}",
                    input_params={"step": "ctr_check"},
                )
            )
            
            state.ctr_check = ctr_result
            
            logger.info(
                "[SEO] CTR check completed score=%.2f product=%s",
                ctr_result["score"],
                state.product_id,
            )
            
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="deterministic.ctr_check",
                    error=str(e),
                    input_params={"step": "ctr_check"},
                )
            )
            logger.error("[SEO] CTR check failed: %s", e)
        
        return actions, state

    # -------------------------------------------------------------------------
    # FEEDBACK: Record for learning (NO LLM call)
    # -------------------------------------------------------------------------
    async def _feedback_domain(
        self,
        old_state: MissionState,
        new_state: MissionState,
        actions: List[AgentAction],
    ) -> None:
        """Record successful SEO outputs for pattern analysis."""
        if new_state.seo_title or new_state.seo_description:
            await self.memory.record_success(
                self.role_name,
                input_summary=old_state.draft_title or old_state.product_id,
                output_summary=f"SEO: {new_state.seo_title[:50] if new_state.seo_title else 'N/A'}",
            )

    # -------------------------------------------------------------------------
    # Helper: Generate SEO metadata
    # -------------------------------------------------------------------------
    async def _generate_seo(
        self,
        title: str,
        description: str,
        category: str,
        target_locale: str,
        serp_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate SEO metadata using LLM.
        
        Returns dict with seo_title, seo_description, seo_alt_text, seo_insights.
        """
        # Format SERP context
        serp_context = ""
        if serp_results:
            serp_lines = []
            for r in serp_results[:3]:
                serp_lines.append(
                    f"#{r.get('position', '?')}: {r.get('title', 'N/A')}\n"
                    f"   Snippet: {r.get('snippet', 'N/A')[:200]}"
                )
            serp_context = "\n\n".join(serp_lines)
        else:
            serp_context = "No competitor data available."
        
        user_prompt = SEO_USER_PROMPT_TEMPLATE.format(
            title=title,
            category=category,
            target_locale=target_locale,
            description=description[:2000],  # Limit description length
            serp_context=serp_context,
        )
        
        result = await self.services.llm.generate_text(
            prompt=user_prompt,
            system_prompt=SEO_SYSTEM_PROMPT,
            model="gpt-4o-mini",  # Cheaper model for SEO
            temperature=0.3,
        )
        
        # Parse the result
        parsed = self._parse_json_result(result)
        
        # Enforce length constraints
        if parsed.get("seo_title"):
            parsed["seo_title"] = self._clamp_length(parsed["seo_title"], 70)
        if parsed.get("seo_description"):
            parsed["seo_description"] = self._clamp_length(parsed["seo_description"], 160)
        if parsed.get("seo_alt_text"):
            parsed["seo_alt_text"] = self._clamp_length(parsed["seo_alt_text"], 125)
        
        return parsed

    # -------------------------------------------------------------------------
    # Helper: CTR/PST Check (Deterministic)
    # -------------------------------------------------------------------------
    def _check_ctr_pst(
        self,
        description: str,
        seo_description: str,
    ) -> Dict[str, Any]:
        """
        Check content against PST (Pain-Solution-Trust) formula.
        
        This is a deterministic check using regex patterns.
        Returns dict with pain_present, solution_present, trust_present, score, suggestions.
        """
        # Combine description and SEO description for checking
        text = f"{description} {seo_description}".lower()
        
        # Check for Pain/Problem indicators
        pain_present = any(
            re.search(pattern, text, re.IGNORECASE)
            for pattern in PST_PAIN_PATTERNS
        )
        
        # Check for Solution/Benefit indicators
        solution_present = any(
            re.search(pattern, text, re.IGNORECASE)
            for pattern in PST_SOLUTION_PATTERNS
        )
        
        # Check for Trust indicators
        trust_present = any(
            re.search(pattern, text, re.IGNORECASE)
            for pattern in PST_TRUST_PATTERNS
        )
        
        # Calculate score (each component = 0.33)
        score = 0.0
        if pain_present:
            score += 0.33
        if solution_present:
            score += 0.34
        if trust_present:
            score += 0.33
        
        # Generate suggestions
        suggestions = []
        if not pain_present:
            suggestions.append("Add a question or pain point to hook readers")
        if not solution_present:
            suggestions.append("Include a concrete benefit with a specific feature/spec")
        if not trust_present:
            suggestions.append("Add a trust cue (origin, craftsmanship, guarantee, shipping)")
        
        return {
            "pain_present": pain_present,
            "solution_present": solution_present,
            "trust_present": trust_present,
            "score": round(score, 2),
            "suggestions": suggestions,
        }

    # -------------------------------------------------------------------------
    # Helper: Parse JSON result
    # -------------------------------------------------------------------------
    def _parse_json_result(self, result: str) -> Dict[str, Any]:
        """Parse JSON from LLM result, with fallback to empty dict."""
        try:
            from src.main.utils.llm_parser import parse_llm_json
            parsed = parse_llm_json(result)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:
            logger.warning("[SEO] Failed to parse JSON: %s", e)
        
        return {}

    # -------------------------------------------------------------------------
    # Helper: Clamp string length
    # -------------------------------------------------------------------------
    def _clamp_length(self, s: str, max_len: int) -> str:
        """Clamp string to max length, trying to break at word boundary."""
        s = (s or "").strip()
        if len(s) <= max_len:
            return s
        
        cut = s[:max_len]
        # Try to break at last space
        idx = cut.rfind(" ")
        if idx >= int(max_len * 0.6):
            cut = cut[:idx].rstrip()
        
        return cut

"""
MarketingAgent - Handles SEO, CTR optimization, SERP insights, and social hooks.

This agent consolidates all marketing-related functionality:
- SEO generation (title, description, alt text, insights)
- SEO recommendations (competitive edge, buyer intent)
- CTR checking (PST formula validation)
- SERP competitor insights
- Social hooks generation (on-demand)
"""

import re
from typing import List, Tuple, Optional, Dict, Any

from ..base import BaseAgent
from ..state import MissionState
from ..context import AgentContext, AgentPlan, AgentAction
from .prompts import (
    SEO_SYSTEM_PROMPT,
    SEO_USER_PROMPT_TEMPLATE,
    SEO_RECOMMENDATIONS_SYSTEM_PROMPT,
    SEO_RECOMMENDATIONS_USER_PROMPT_TEMPLATE,
    PST_PAIN_PATTERNS,
    PST_SOLUTION_PATTERNS,
    PST_TRUST_PATTERNS,
    SOCIAL_HOOKS_SYSTEM_PROMPT,
    SOCIAL_HOOKS_USER_PROMPT_TEMPLATE,
    SEASONAL_CAPTION_SYSTEM_PROMPT,
    SEASONAL_CAPTION_USER_PROMPT_TEMPLATE,
)
from .schemas import (
    MarketingOutput,
    SEOInsights,
    SEORecommendations,
    CompetitiveEdge,
    BuyerIntent,
    CTRCheck,
    SerpCompetitor,
    SocialHook,
    SeasonalCampaign,
)
from .holidays import (
    get_next_upcoming_holiday,
    generate_discount_code,
    should_show_seasonal_campaign,
)
from src.main.logging.logger import get_logger

logger = get_logger(__name__)


class MarketingAgent(BaseAgent):
    """
    Agent for SEO optimization, CTR checking, and social marketing.
    
    Responsibilities:
    - SEO generation (title, description, alt text, insights)
    - SEO recommendations (competitive edge, buyer intent)
    - CTR/PST formula validation
    - SERP competitor analysis
    - Social hooks/caption generation (automatically in pipeline)
    
    Uses:
    - SerpService for competitor data (Perception) - NO LLM
    - LLM for SEO generation (Action) - 1 LLM call
    - LLM for SEO recommendations (Action) - 1 LLM call
    - Deterministic CTR check - NO LLM
    - LLM for social hooks (Action) - 1 LLM call
    """
    
    role_name = "Marketing"
    default_tool = "llm.generate_text"
    
    # NOTE: requires_llm_reasoning = False (default)
    # Reasoning phase uses deterministic plan - NO LLM call

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
                        "[Marketing] Loaded %d SERP results for query=%s",
                        len(serp_results),
                        search_query[:50],
                    )
            except Exception as e:
                logger.warning(
                    "[Marketing] SERP fetch failed query=%s err=%s",
                    search_query[:50],
                    e,
                )
                context.serp_results = []
        else:
            context.serp_results = []
        
        return context

    # -------------------------------------------------------------------------
    # ACTION: Generate SEO + recommendations + CTR check
    # -------------------------------------------------------------------------
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Execute marketing actions:
        1. Generate SEO metadata (1 LLM call)
        2. Generate SEO recommendations (1 LLM call)
        3. Run CTR/PST check (deterministic)
        4. Generate social hooks/captions (1 LLM call)
        """
        actions = []
        
        # Get product data
        title = context.get_product_title()
        description = state.draft_content or context.get_product_description()
        category = context.get_category()
        target_locale = state.target_locale or state.raw_input.get("target_locale", "en")
        
        # Store SERP insights in state
        state.serp_insights = getattr(context, 'serp_results', [])
        
        # -----------------------------------------------------------------
        # Step 1: Generate SEO metadata (1 LLM call)
        # -----------------------------------------------------------------
        try:
            seo_result = await self._generate_seo(
                title=title,
                description=description,
                category=category,
                target_locale=target_locale,
                serp_results=context.serp_results if hasattr(context, 'serp_results') else [],
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
                "[Marketing] SEO generated for product=%s shop=%s",
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
            logger.error("[Marketing] SEO generation failed: %s", e)
        
        # -----------------------------------------------------------------
        # Step 2: Generate SEO recommendations (1 LLM call)
        # -----------------------------------------------------------------
        try:
            recs_result = await self._generate_seo_recommendations(
                product_name=title,
                description=description,
                category=category,
                target_locale=target_locale,
                seo_title=state.seo_title or "",
                seo_description=state.seo_description or "",
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_text",
                    output="SEO recommendations generated",
                    input_params={"step": "seo_recommendations"},
                )
            )
            
            state.seo_recommendations = recs_result
            
            logger.info(
                "[Marketing] SEO recommendations generated for product=%s",
                state.product_id,
            )
            
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"step": "seo_recommendations"},
                )
            )
            logger.error("[Marketing] SEO recommendations failed: %s", e)
        
        # -----------------------------------------------------------------
        # Step 3: Run CTR/PST check (deterministic - NO LLM)
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
                "[Marketing] CTR check completed score=%.2f product=%s",
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
            logger.error("[Marketing] CTR check failed: %s", e)
        
        # -----------------------------------------------------------------
        # Step 4: Generate social hooks/captions (1 LLM call)
        # -----------------------------------------------------------------
        try:
            # Get product tags if available
            product_tags = state.raw_input.get("tags", [])
            if isinstance(product_tags, str):
                product_tags = [t.strip() for t in product_tags.split(",") if t.strip()]
            
            hooks_result = await self.generate_social_hooks(
                product_title=title,
                category=category,
                tags=product_tags,
                focus="Instagram Reels",
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_text",
                    output=f"Generated {len(hooks_result.get('hooks', []))} social hooks",
                    input_params={"step": "social_hooks"},
                )
            )
            
            # Store hooks in state
            state.social_hooks = hooks_result.get("hooks", [])
            
            logger.info(
                "[Marketing] Social hooks generated count=%d product=%s",
                len(state.social_hooks or []),
                state.product_id,
            )
            
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"step": "social_hooks"},
                )
            )
            logger.error("[Marketing] Social hooks generation failed: %s", e)
            # Non-critical - continue without social hooks
            state.social_hooks = []
        
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
        """Record successful marketing outputs for pattern analysis."""
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
    # Helper: Generate SEO recommendations
    # -------------------------------------------------------------------------
    async def _generate_seo_recommendations(
        self,
        product_name: str,
        description: str,
        category: str,
        target_locale: str,
        seo_title: str,
        seo_description: str,
    ) -> Dict[str, Any]:
        """
        Generate SEO recommendations using LLM.
        
        Returns dict with competitive_edge and buyer_intent.
        """
        user_prompt = SEO_RECOMMENDATIONS_USER_PROMPT_TEMPLATE.format(
            product_name=product_name,
            category=category,
            target_locale=target_locale,
            description=description[:2000],
            seo_title=seo_title,
            seo_description=seo_description,
        )
        
        result = await self.services.llm.generate_text(
            prompt=user_prompt,
            system_prompt=SEO_RECOMMENDATIONS_SYSTEM_PROMPT,
            model="gpt-4o-mini",  # Cheaper model
            temperature=0.0,
        )
        
        return self._parse_json_result(result)

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
    # Generate Social Hooks (called in pipeline and can be called on-demand)
    # -------------------------------------------------------------------------
    async def generate_social_hooks(
        self,
        product_title: str,
        category: str,
        tags: Optional[List[str]] = None,
        focus: str = "Instagram Reels",
    ) -> Dict[str, Any]:
        """
        Generate social media hooks/captions for a product.
        
        This is called automatically in the agent pipeline (Step 4) and
        can also be called on-demand for standalone caption generation.
        
        Args:
            product_title: Product title
            category: Product category
            tags: Product tags (optional)
            focus: Content format focus (default: Instagram Reels)
        
        Returns:
            Dict with hooks and overlay_suggestions
        """
        tags_str = ", ".join(tags[:10]) if tags else ""
        
        user_prompt = SOCIAL_HOOKS_USER_PROMPT_TEMPLATE.format(
            focus=focus,
            product_title=product_title,
            category=category,
            tags=tags_str,
        )
        
        result = await self.services.llm.generate_text(
            prompt=user_prompt,
            system_prompt=SOCIAL_HOOKS_SYSTEM_PROMPT,
            model="gpt-4o-mini",
            temperature=0.8,  # More creative for social content
        )
        
        parsed = self._parse_json_result(result)
        
        # Normalize hooks
        hooks = parsed.get("hooks", [])
        normalized_hooks = []
        
        for h in hooks[:3]:
            caption = str(h.get("caption", "")).strip()
            hashtags = h.get("hashtags", [])
            
            # Clean hashtags
            clean_hashtags = []
            for tag in hashtags:
                tag = str(tag).strip()
                if tag and not tag.startswith("#"):
                    tag = f"#{tag}"
                if tag:
                    clean_hashtags.append(tag)
            
            # Build copy_text
            copy_text = caption
            if clean_hashtags:
                copy_text = f"{caption}\n\n{' '.join(clean_hashtags)}"
            
            normalized_hooks.append({
                "type": str(h.get("type", "Hook")).strip(),
                "caption": caption,
                "hashtags": clean_hashtags[:12],
                "overlay": str(h.get("overlay", "")).strip()[:28],
                "copy_text": copy_text,
            })
        
        return {
            "hooks": normalized_hooks,
            "overlay_suggestions": parsed.get("overlay_suggestions", [])[:5],
        }

    # -------------------------------------------------------------------------
    # On-demand: Generate Seasonal Campaign
    # -------------------------------------------------------------------------
    async def generate_seasonal_campaign(
        self,
        product_title: str,
        category: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate seasonal campaign data and caption.
        
        This is called on-demand, not as part of the main pipeline.
        
        Args:
            product_title: Product title
            category: Product category
        
        Returns:
            Dict with campaign data and caption, or None if no upcoming holiday
        """
        from datetime import date
        
        today = date.today()
        holiday = get_next_upcoming_holiday(today)
        
        if not holiday or not should_show_seasonal_campaign(holiday, today):
            return None
        
        days_until = (holiday.date - today).days
        discount_code = generate_discount_code(holiday.name, category, holiday.date.year)
        campaign_title = f"{holiday.name} {category} Campaign"
        
        # Generate caption
        user_prompt = SEASONAL_CAPTION_USER_PROMPT_TEMPLATE.format(
            holiday_name=holiday.name,
            holiday_date=holiday.date.isoformat(),
            days_until=days_until,
            product_title=product_title,
            category=category,
        )
        
        result = await self.services.llm.generate_text(
            prompt=user_prompt,
            system_prompt=SEASONAL_CAPTION_SYSTEM_PROMPT,
            model="gpt-4o-mini",
            temperature=0.8,
        )
        
        parsed = self._parse_json_result(result)
        
        return {
            "holiday": {
                "name": holiday.name,
                "date": holiday.date.isoformat(),
                "days_until": days_until,
            },
            "campaign": {
                "title": campaign_title,
                "discount_code": discount_code,
            },
            "caption": parsed.get("caption", ""),
            "cta": parsed.get("cta", ""),
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
            logger.warning("[Marketing] Failed to parse JSON: %s", e)
        
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

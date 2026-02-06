"""
MarketingAgent - Handles social media captions and hooks.

This agent focuses on social media marketing:
- Social hooks/caption generation (Instagram Reels, TikTok)
- Seasonal campaign generation

SEO functionality has been moved to the dedicated SEOAgent.
"""

from typing import List, Tuple, Optional, Dict, Any

from ..base import BaseAgent
from ..state import MissionState
from ..context import AgentContext, AgentPlan, AgentAction
from .prompts import (
    SOCIAL_HOOKS_SYSTEM_PROMPT,
    SOCIAL_HOOKS_USER_PROMPT_TEMPLATE,
    SEASONAL_CAPTION_SYSTEM_PROMPT,
    SEASONAL_CAPTION_USER_PROMPT_TEMPLATE,
)
from .schemas import (
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
    Agent for social media marketing and caption generation.
    
    Responsibilities:
    - Social hooks/caption generation (automatically in pipeline)
    - Seasonal campaign generation (on-demand)
    
    LLM Calls: 1 (for social hooks generation)
    
    Note: SEO functionality is handled by the dedicated SEOAgent.
    """
    
    role_name = "Marketing"
    default_tool = "llm.generate_text"
    
    # NOTE: requires_llm_reasoning = False (default)
    # Reasoning phase uses deterministic plan - NO LLM call

    # -------------------------------------------------------------------------
    # PERCEPTION: No external data needed for social hooks
    # -------------------------------------------------------------------------
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """
        Perception phase - no external data needed for social hooks.
        
        Product data is already available in context.
        """
        logger.info(
            "[Marketing] Starting social hooks generation for product=%s shop=%s",
            state.product_id,
            self.shop_id,
        )
        return context

    # -------------------------------------------------------------------------
    # ACTION: Generate social hooks/captions
    # -------------------------------------------------------------------------
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Execute marketing actions:
        1. Generate social hooks/captions (1 LLM call)
        """
        actions = []
        
        # Get product data
        title = context.get_product_title()
        category = context.get_category()
        
        # -----------------------------------------------------------------
        # Generate social hooks/captions (1 LLM call)
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
        if new_state.social_hooks:
            await self.memory.record_success(
                self.role_name,
                input_summary=old_state.draft_title or old_state.product_id,
                output_summary=f"Social hooks: {len(new_state.social_hooks)} generated",
            )

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
        
        This is called automatically in the agent pipeline and
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

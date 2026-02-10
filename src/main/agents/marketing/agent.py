"""
MarketingAgent - Handles social media captions and hooks.

This agent focuses on social media marketing:
- Social hooks/caption generation (Instagram Reels, TikTok)
- Seasonal campaign generation

SEO functionality has been moved to the dedicated SEOAgent.
"""

import json
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
    - Email marketing (launch, abandoned cart, welcome)
    - Ad copy generation (social, search)
    
    LLM Calls: 1 (for content generation)
    
    Note: SEO functionality is handled by the dedicated SEOAgent.
    
    Supports multiple templates:
    - marketing/social-tiktok: TikTok / social media hooks
    - marketing/email-launch: Product launch emails
    - marketing/email-abandoned: Abandoned cart emails
    - marketing/email-welcome: Welcome emails
    - marketing/ad-facebook: Facebook/Instagram ads
    - marketing/ad-google: Google Ads
    """
    
    role_name = "Marketing"
    default_tool = "llm.generate_text"
    
    # Supported templates
    SUPPORTED_TEMPLATES = [
        "marketing/social-tiktok",
        "marketing/email-launch",
        "marketing/email-abandoned",
        "marketing/email-welcome",
        "marketing/ad-facebook",
        "marketing/ad-google",
    ]
    
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
        Execute marketing actions with template routing.
        
        Routes to appropriate generator based on template_id.
        """
        actions = []
        
        # Get template ID (default to social if not specified)
        template_id = state.raw_input.get("template_id", "marketing/social-tiktok")
        
        # Route to appropriate generator
        if template_id.startswith("marketing/social"):
            return await self._generate_social(state, context, actions, template_id)
        elif template_id.startswith("marketing/email"):
            return await self._generate_email(state, context, actions, template_id)
        elif template_id.startswith("marketing/ad"):
            return await self._generate_ad(state, context, actions, template_id)
        else:
            # Fallback to social
            logger.warning(
                "[Marketing] Unknown template_id=%s, falling back to social",
                template_id,
            )
            return await self._generate_social(state, context, actions, "marketing/social-tiktok")

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
    
    # -------------------------------------------------------------------------
    # Template-specific generators
    # -------------------------------------------------------------------------
    
    def _build_system_prompt(
        self,
        state: MissionState,
        context: AgentContext,
        template_id: str,
    ) -> str:
        """Build system prompt with operational rules and template-specific prompt."""
        prompt_parts = []
        
        # NEW: Inject operational rules FIRST (highest priority)
        operational_rules = context.get_operational_rules_prompt()
        if operational_rules:
            prompt_parts.append(operational_rules)
        
        # Get template-specific system prompt
        from src.main.agents.templates import get_template
        template = get_template(template_id)
        if template and template.system_prompt:
            prompt_parts.append(template.system_prompt)
        else:
            # Fallback to social hooks prompt for social templates
            if template_id.startswith("marketing/social"):
                prompt_parts.append(SOCIAL_HOOKS_SYSTEM_PROMPT)
        
        return "\n\n".join(prompt_parts)
    
    def _build_user_prompt(
        self,
        state: MissionState,
        context: AgentContext,
        template_id: str,
    ) -> str:
        """Build user prompt from template."""
        from src.main.agents.templates import get_template
        template = get_template(template_id)
        
        if template and template.user_prompt_template:
            # Build format dict
            title = context.get_product_title()
            category = context.get_category()
            description = context.get_product_description()
            target_locale = state.target_locale or state.raw_input.get("target_locale", "en")
            
            format_dict = {
                "title": title,
                "product_title": title,  # Alias
                "category": category,
                "description": description,
                "target_locale": target_locale,
                **state.raw_input,  # Include any additional inputs
            }
            
            try:
                return template.user_prompt_template.format(**format_dict)
            except KeyError as e:
                logger.warning(
                    "[Marketing] Missing template variable %s, using defaults",
                    e,
                )
                return template.user_prompt_template.format(
                    title=title,
                    category=category,
                    target_locale=target_locale,
                    description=description,
                )
        
        # Fallback for social hooks
        if template_id.startswith("marketing/social"):
            product_tags = state.raw_input.get("tags", [])
            if isinstance(product_tags, str):
                product_tags = [t.strip() for t in product_tags.split(",") if t.strip()]
            tags_str = ", ".join(product_tags[:10]) if product_tags else ""
            
            return SOCIAL_HOOKS_USER_PROMPT_TEMPLATE.format(
                focus="Instagram Reels",
                product_title=context.get_product_title(),
                category=context.get_category(),
                tags=tags_str,
            )
        
        return ""
    
    async def _generate_social(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
        template_id: str,
    ) -> Tuple[List[AgentAction], MissionState]:
        """Generate social media content (existing flow)."""
        try:
            product_tags = state.raw_input.get("tags", [])
            if isinstance(product_tags, str):
                product_tags = [t.strip() for t in product_tags.split(",") if t.strip()]
            
            hooks_result = await self.generate_social_hooks(
                product_title=context.get_product_title(),
                category=context.get_category(),
                tags=product_tags,
                focus="Instagram Reels" if "instagram" in template_id else "TikTok",
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_text",
                    output=f"Generated {len(hooks_result.get('hooks', []))} social hooks",
                    input_params={"template_id": template_id},
                )
            )
            
            state.social_hooks = hooks_result.get("hooks", [])
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Marketing] Social content generated template=%s product=%s",
                template_id,
                state.product_id,
            )
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"template_id": template_id},
                )
            )
            state.set_error(f"Social content generation failed: {str(e)}")
        
        return actions, state
    
    async def _generate_email(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
        template_id: str,
    ) -> Tuple[List[AgentAction], MissionState]:
        """Generate email content using template."""
        system_prompt = self._build_system_prompt(state, context, template_id)
        user_prompt = self._build_user_prompt(state, context, template_id)
        
        try:
            result = await self.services.llm.generate_text(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model="gpt-4o",
                temperature=0.7,
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_text",
                    output=result,
                    input_params={"template_id": template_id},
                )
            )
            
            parsed = self._parse_json_result(result)
            state.draft_content = json.dumps(parsed)  # Store email content as valid JSON
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Marketing] Email generated template=%s shop=%s",
                template_id,
                self.shop_id,
            )
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"template_id": template_id},
                )
            )
            state.set_error(f"Email generation failed: {str(e)}")
        
        return actions, state
    
    async def _generate_ad(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
        template_id: str,
    ) -> Tuple[List[AgentAction], MissionState]:
        """Generate ad copy using template."""
        system_prompt = self._build_system_prompt(state, context, template_id)
        user_prompt = self._build_user_prompt(state, context, template_id)
        
        try:
            result = await self.services.llm.generate_text(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model="gpt-4o-mini",  # Cheaper model for ad copy
                temperature=0.7,
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_text",
                    output=result,
                    input_params={"template_id": template_id},
                )
            )
            
            parsed = self._parse_json_result(result)
            state.draft_content = json.dumps(parsed)  # Store ad copy as valid JSON
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Marketing] Ad copy generated template=%s shop=%s",
                template_id,
                self.shop_id,
            )
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"template_id": template_id},
                )
            )
            state.set_error(f"Ad copy generation failed: {str(e)}")
        
        return actions, state
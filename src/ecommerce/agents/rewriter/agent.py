"""
RewriterAgent - Generates optimized product copy using RAG and LLM.

This agent handles the creative content generation for product descriptions
and titles. It uses brand context from RAG to ensure brand-consistent messaging.

NOTE: SEO generation is handled by SEOAgent for all tiers.
"""

import json
from typing import Dict, List, Optional, Tuple

from src.agentic_core.agents.base import BaseAgent
from src.ecommerce.state import ShopifyMissionState as MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction
from .prompts import (
    REWRITER_SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    TONE_PROMPTS,
    VALUE_DISCOVERY_PROMPT,
    BRAND_CONTEXT_INJECTION_TEMPLATE,
    LEARNED_PREFERENCES_TEMPLATE,
    LOCALE_PERSONA_TEMPLATE,
    COMPLIANCE_FEEDBACK_TEMPLATE,
    REWRITER_REFINE_PROMPT,
    REFINE_USER_PROMPT,
)
from src.ecommerce.config.shopify_config import LOCALE_PERSONA_MAP
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)


class RewriterAgent(BaseAgent):
    """
    Agent for generating optimized product copy.
    
    Uses:
    - RAG for brand context retrieval (Perception)
    - Deterministic planning (Reasoning) 
    - LLM for content generation (Action) - SINGLE LLM CALL
    
    The agent transforms product data into compelling marketing copy
    that is localized and brand-consistent.
    
    NOTE: SEO is handled by SEOAgent for all tiers.
    
    Supports multiple templates:
    - product/description: Product description (existing rewriter flow)
    - product/collection: Collection description
    - product/faq: Product FAQ generator
    - product/landing-hero: Landing page hero section
    - product/blog-post: Brand blog post (manufacturing, artisan techniques, etc.)
    """
    
    role_name = "Rewriter"
    default_tool = "llm.generate_text"
    
    # Supported templates
    SUPPORTED_TEMPLATES = [
        "product/description",
        "product/collection",
        "product/faq",
        "product/landing-hero",
        "product/blog-post",
    ]
    
    # NOTE: requires_llm_reasoning = False (default)
    # Reasoning phase uses deterministic plan - NO LLM call

    # ── Autonomous Publish Map ────────────────────────────────────────
    # Maps template_id → async handler(self, state, creds) for autonomous publishing.
    PUBLISH_MAP: Dict[str, "Callable"] = {
        "product/description": "_publish_product_body",
        "product/faq": "_publish_faq_append",
        "product/landing-hero": "_publish_hero_overwrite",
        "product/blog-post": "_publish_article",
        "product/collection": "_publish_collection",
    }

    async def _publish_product_body(self, state, creds):
        """Push draft_content → Shopify descriptionHtml (delegated to adapter)."""
        await self.services.publish_adapter.publish_product_body(state, creds)

    async def _publish_faq_append(self, state, creds):
        """Convert FAQ JSON → HTML and append to product description (delegated to adapter)."""
        await self.services.publish_adapter.publish_faq_append(state, creds)

    async def _publish_hero_overwrite(self, state, creds):
        """Convert Hero JSON → HTML and overwrite hero section (delegated to adapter)."""
        await self.services.publish_adapter.publish_hero_overwrite(state, creds)

    async def _publish_article(self, state, creds):
        """Push blog-post draft_content → Shopify article (delegated to adapter)."""
        await self.services.publish_adapter.publish_article(state, creds)

    async def _publish_collection(self, state, creds):
        """Create a Shopify collection from draft_content (delegated to adapter)."""
        await self.services.publish_adapter.publish_collection(state, creds)

    # -------------------------------------------------------------------------
    # PERCEPTION: Gather brand context (NO LLM call)
    # -------------------------------------------------------------------------
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """
        Gather brand context via RAG embedding search.
        
        This fetches relevant brand story/pillars to inject into the
        generation prompt for brand-consistent copy.
        """
        # Build product text for embedding search
        product_text = f"{context.get_product_title()} {context.get_product_description()}"
        
        # Fetch brand context via RAG (embedding similarity - not LLM)
        if state.db:
            try:
                brand_chunks = await self.services.rag.get_brand_context(
                    db=state.db,
                    shop_id=self.shop_id,
                    product_text=product_text,
                    limit=3,
                )
                context.brand_context = brand_chunks
                
                if brand_chunks:
                    logger.info(
                        "[Rewriter] Loaded %d brand context chunks for shop=%s",
                        len(brand_chunks),
                        self.shop_id,
                    )
            except Exception as e:
                logger.warning(
                    "[Rewriter] Failed to load brand context shop=%s err=%s",
                    self.shop_id,
                    e,
                )
        
        return context

    # NOTE: _create_default_plan inherited - uses deterministic plan
    # This saves 1 LLM call per agent execution!

    # -------------------------------------------------------------------------
    # ACTION: Generate copy (SINGLE LLM CALL)
    # -------------------------------------------------------------------------
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Generate product copy using LLM.
        
        This is the ONLY LLM call for this agent.
        
        Supports two modes:
        - Fresh Run: Generate from scratch using source data
        - Refinement Mode: Modify existing draft based on user feedback
        """
        actions = []
        
        # Check for refinement mode
        feedback = state.raw_input.get("_regeneration_feedback")
        previous_draft = self._get_previous_draft(state)
        
        if feedback and previous_draft:
            # === REFINEMENT MODE ===
            state.add_log("Rewriter: Refinement Mode Active")
            logger.info(
                "[Rewriter] Refinement mode for product=%s shop=%s feedback_len=%d",
                state.product_id,
                self.shop_id,
                len(feedback),
            )
            actions, state = await self._run_refinement(
                state, context, feedback, previous_draft, actions
            )
        else:
            # === FRESH RUN ===
            actions, state = await self._run_fresh_generation(
                state, context, actions
            )
        
        return actions, state

    async def _run_fresh_generation(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Run fresh content generation from scratch.
        
        Uses the full REWRITER_SYSTEM_PROMPT to generate new content.
        Supports template routing for different content types.
        """
        # Check for template ID
        template_id = state.raw_input.get("template_id", "product/description")
        
        # Route to appropriate generator based on template
        if template_id == "product/description":
            # Existing product description flow
            return await self._generate_description(state, context, actions)
        elif template_id == "product/collection":
            return await self._generate_collection(state, context, actions)
        elif template_id == "product/faq":
            return await self._generate_faq(state, context, actions)
        elif template_id == "product/landing-hero":
            return await self._generate_landing_hero(state, context, actions)
        elif template_id == "product/blog-post":
            return await self._generate_blog_post(state, context, actions)
        else:
            # Fallback to description
            logger.warning(
                "[Rewriter] Unknown template_id=%s, falling back to product/description",
                template_id,
            )
            return await self._generate_description(state, context, actions)
    
    async def _generate_description(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
    ) -> Tuple[List[AgentAction], MissionState]:
        """Generate product description (existing flow)."""
        # Build prompts with brand context and learned rules
        system_prompt = self._build_system_prompt(state, context, "product/description")
        user_prompt = self._build_user_prompt(state, context, "product/description")
        
        try:
            # === THE ONLY LLM CALL FOR THIS AGENT ===
            result = await self.services.llm.generate_text(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model="gpt-4o",  # Best model for creative work
                temperature=0.7,
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_text",
                    output=result,
                    input_params={"prompt_len": len(user_prompt), "mode": "fresh"},
                )
            )
            
            # Parse the result and update state
            parsed = self._parse_llm_result(result)
            
            state.draft_content = parsed.get("description", result)
            state.draft_title = parsed.get("title", "")
            state.discovered_values = parsed.get("discovered_values", [])
            # NOTE: SEO is handled by SEOAgent for all tiers
            
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Rewriter] Generated content for product=%s shop=%s",
                state.product_id,
                self.shop_id,
            )
            
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"prompt_len": len(user_prompt) if user_prompt else 0, "mode": "fresh"},
                )
            )
            state.set_error(f"Content generation failed: {str(e)}")
        
        return actions, state

    async def _run_refinement(
        self,
        state: MissionState,
        context: AgentContext,
        feedback: str,
        previous_draft: dict,
        actions: List[AgentAction],
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Run refinement mode - modify existing draft based on user feedback.
        
        Uses REWRITER_REFINE_PROMPT to make targeted edits only.
        """
        # Build the refinement prompt with current draft and feedback
        system_prompt = REWRITER_REFINE_PROMPT.format(
            current_title=previous_draft.get("title", ""),
            current_description=previous_draft.get("description", ""),
            user_feedback=feedback,
            source_title=context.get_product_title(),
            category=context.get_category(),
            source_description=context.get_product_description()[:3000],  # Limit length
        )
        
        user_prompt = REFINE_USER_PROMPT
        
        try:
            # === REFINEMENT LLM CALL ===
            result = await self.services.llm.generate_text(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model="gpt-4o",  # Best model for creative work
                temperature=0.5,  # Lower temperature for more controlled edits
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_text",
                    output=result,
                    input_params={
                        "prompt_len": len(system_prompt) + len(user_prompt),
                        "mode": "refinement",
                        "feedback_len": len(feedback),
                    },
                )
            )
            
            # Parse the result and update state
            parsed = self._parse_llm_result(result)
            
            state.draft_content = parsed.get("description", previous_draft.get("description", ""))
            state.draft_title = parsed.get("title", previous_draft.get("title", ""))
            state.discovered_values = parsed.get(
                "discovered_values",
                previous_draft.get("discovered_values", [])
            )
            
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Rewriter] Refined content for product=%s shop=%s",
                state.product_id,
                self.shop_id,
            )
            
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"mode": "refinement"},
                )
            )
            state.set_error(f"Content refinement failed: {str(e)}")
        
        return actions, state

    def _get_previous_draft(self, state: MissionState) -> Optional[dict]:
        """
        Get the previous draft content for refinement mode.
        
        Checks multiple sources:
        1. state.draft_content / state.draft_title (if already set)
        2. state.agent_outputs["RewriterAgent"] (from previous run)
        
        Returns:
            Dict with title, description, discovered_values or None if no draft exists
        """
        # Check if draft is already in state
        if state.draft_content or state.draft_title:
            return {
                "title": state.draft_title or "",
                "description": state.draft_content or "",
                "discovered_values": state.discovered_values or [],
            }
        
        # Check agent_outputs from previous run
        rewriter_output = state.agent_outputs.get("RewriterAgent", {})
        if rewriter_output:
            return {
                "title": rewriter_output.get("draft_title", ""),
                "description": rewriter_output.get("draft_content", ""),
                "discovered_values": rewriter_output.get("discovered_values", []),
            }
        
        return None

    # -------------------------------------------------------------------------
    # FEEDBACK: Record for learning (NO LLM call)
    # -------------------------------------------------------------------------
    async def _feedback_domain(
        self,
        old_state: MissionState,
        new_state: MissionState,
        actions: List[AgentAction],
    ) -> None:
        """Record successful generations for pattern analysis."""
        if new_state.status == "DRAFT_READY":
            await self.memory.record_success(
                self.role_name,
                input_summary=old_state.raw_input.get("title", "")[:50],
                output_summary=(
                    new_state.draft_content[:100]
                    if new_state.draft_content
                    else ""
                ),
            )

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------
    def _build_system_prompt(
        self,
        state: MissionState,
        context: AgentContext,
        template_id: Optional[str] = None,
    ) -> str:
        """Build system prompt with brand context and locale persona."""
        prompt_parts = []
        
        # NEW: Inject operational rules FIRST (highest priority)
        operational_rules = context.get_operational_rules_prompt()
        if operational_rules:
            prompt_parts.append(operational_rules)
        
        # Get template-specific system prompt if available
        if template_id and template_id != "product/description":
            from src.ecommerce.templates import get_template
            template = get_template(template_id)
            if template and template.system_prompt:
                prompt_parts.append(template.system_prompt)
            else:
                # Fallback to base prompt
                prompt_parts.append(REWRITER_SYSTEM_PROMPT)
        else:
            # Start with base system prompt
            prompt_parts.append(REWRITER_SYSTEM_PROMPT)
        
        # Add value discovery prompt
        prompt_parts.append(VALUE_DISCOVERY_PROMPT)
        
        # Add tone (default to professional)
        tone = state.raw_input.get("tone", "professional")
        if tone in TONE_PROMPTS:
            prompt_parts.append(TONE_PROMPTS[tone])
        
        # Add locale persona if available
        target_locale = state.target_locale or state.raw_input.get("target_locale", "en")
        if target_locale in LOCALE_PERSONA_MAP:
            prompt_parts.append(
                LOCALE_PERSONA_TEMPLATE.format(persona=LOCALE_PERSONA_MAP[target_locale])
            )
        
        # Add brand context if available
        brand_text = context.get_brand_context_text()
        if brand_text:
            brand_injection = BRAND_CONTEXT_INJECTION_TEMPLATE.format(
                context=brand_text
            )
            prompt_parts.append(brand_injection)
        
        # Add learned preferences if available
        learned_rules = context.get_learned_rules_text()
        if learned_rules:
            prompt_parts.append(
                LEARNED_PREFERENCES_TEMPLATE.format(rules=learned_rules)
            )
        
        # Add compliance feedback if this is a regeneration
        compliance_feedback = state.raw_input.get("compliance_feedback")
        if compliance_feedback:
            prompt_parts.append(
                COMPLIANCE_FEEDBACK_TEMPLATE.format(feedback=compliance_feedback)
            )
        
        return "\n\n".join(prompt_parts)

    def _build_user_prompt(
        self,
        state: MissionState,
        context: AgentContext,
        template_id: Optional[str] = None,
    ) -> str:
        """Build user prompt with product data."""
        # Get template-specific user prompt if available
        if template_id and template_id != "product/description":
            from src.ecommerce.templates import get_template
            template = get_template(template_id)
            if template and template.user_prompt_template:
                # Format template with available data
                title = context.get_product_title()
                description = context.get_product_description()
                category = context.get_category()
                target_locale = state.target_locale or state.raw_input.get("target_locale", "en")
                
                # Smart defaults for mission-mode (when template fields aren't
                # explicitly provided via the Content Templates page).
                smart_defaults = {
                    "topic": title,                      # blog-post
                    "context": description,              # blog-post
                    "collection_name": title,            # collection
                    "products": description,             # collection
                }
                
                # Build format dict: smart defaults → standard fields → raw_input overrides
                format_dict = {
                    **smart_defaults,
                    "title": title,
                    "description": description,
                    "category": category,
                    "target_locale": target_locale,
                    **state.raw_input,  # Explicit inputs always win
                }
                
                try:
                    return template.user_prompt_template.format(**format_dict)
                except KeyError as e:
                    logger.warning(
                        "[Rewriter] Missing template variable %s, using defaults",
                        e,
                    )
                    # Robust fallback: extract all {var} names and default to ""
                    import re
                    var_names = re.findall(r"\{(\w+)\}", template.user_prompt_template)
                    safe_dict = {v: "" for v in var_names}
                    safe_dict.update(format_dict)
                    return template.user_prompt_template.format(**safe_dict)
        
        # Default: product description prompt
        title = context.get_product_title()
        description = context.get_product_description()
        category = context.get_category()
        target_locale = state.target_locale or state.raw_input.get("target_locale", "en")
        
        return USER_PROMPT_TEMPLATE.format(
            title=title,
            category=category,
            target_locale=target_locale,
            description=description,
        )

    def _parse_llm_result(self, result: str) -> dict:
        """
        Parse the LLM JSON result.
        
        Falls back to raw result if parsing fails.
        """
        try:
            from src.shared.utils.llm_parser import parse_llm_json
            
            parsed = parse_llm_json(result)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:
            logger.warning("[Rewriter] Failed to parse LLM result: %s", e)
        
        # Fallback: return raw content as description
        return {"description": result}
    
    # -------------------------------------------------------------------------
    # Template-specific generators
    # -------------------------------------------------------------------------
    
    async def _generate_blog_post(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
    ) -> Tuple[List[AgentAction], MissionState]:
        """Generate brand blog post using template."""
        system_prompt = self._build_system_prompt(state, context, "product/blog-post")
        user_prompt = self._build_user_prompt(state, context, "product/blog-post")
        
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
                    input_params={"template_id": "product/blog-post", "mode": "fresh"},
                )
            )
            
            parsed = self._parse_llm_result(result)
            state.draft_title = parsed.get("title", "")
            state.draft_content = json.dumps(parsed)  # Store blog post as valid JSON
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Rewriter] Generated blog post for shop=%s topic=%s",
                self.shop_id,
                state.raw_input.get("topic", ""),
            )
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"template_id": "product/blog-post"},
                )
            )
            state.set_error(f"Blog post generation failed: {str(e)}")
        
        return actions, state
    
    async def _generate_collection(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
    ) -> Tuple[List[AgentAction], MissionState]:
        """Generate collection description using template."""
        system_prompt = self._build_system_prompt(state, context, "product/collection")
        user_prompt = self._build_user_prompt(state, context, "product/collection")
        
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
                    input_params={"template_id": "product/collection", "mode": "fresh"},
                )
            )
            
            parsed = self._parse_llm_result(result)
            state.draft_content = json.dumps(parsed)  # Store collection as valid JSON
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Rewriter] Generated collection description shop=%s",
                self.shop_id,
            )
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"template_id": "product/collection"},
                )
            )
            state.set_error(f"Collection generation failed: {str(e)}")
        
        return actions, state
    
    async def _generate_faq(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
    ) -> Tuple[List[AgentAction], MissionState]:
        """Generate product FAQ using template."""
        system_prompt = self._build_system_prompt(state, context, "product/faq")
        user_prompt = self._build_user_prompt(state, context, "product/faq")
        
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
                    input_params={"template_id": "product/faq", "mode": "fresh"},
                )
            )
            
            parsed = self._parse_llm_result(result)
            state.draft_content = json.dumps(parsed)  # Store FAQs as valid JSON
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Rewriter] Generated FAQ for product=%s shop=%s",
                state.product_id,
                self.shop_id,
            )
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"template_id": "product/faq"},
                )
            )
            state.set_error(f"FAQ generation failed: {str(e)}")
        
        return actions, state
    
    async def _generate_landing_hero(
        self,
        state: MissionState,
        context: AgentContext,
        actions: List[AgentAction],
    ) -> Tuple[List[AgentAction], MissionState]:
        """Generate landing page hero section using template."""
        system_prompt = self._build_system_prompt(state, context, "product/landing-hero")
        user_prompt = self._build_user_prompt(state, context, "product/landing-hero")
        
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
                    input_params={"template_id": "product/landing-hero", "mode": "fresh"},
                )
            )
            
            parsed = self._parse_llm_result(result)
            state.draft_content = json.dumps(parsed)  # Store hero section as valid JSON
            state.status = "DRAFT_READY"
            
            logger.info(
                "[Rewriter] Generated landing hero for product=%s shop=%s",
                state.product_id,
                self.shop_id,
            )
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_text",
                    error=str(e),
                    input_params={"template_id": "product/landing-hero"},
                )
            )
            state.set_error(f"Landing hero generation failed: {str(e)}")
        
        return actions, state


# Backward compatibility alias
CopywriterAgent = RewriterAgent

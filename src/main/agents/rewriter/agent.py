"""
RewriterAgent - Generates optimized product copy using RAG and LLM.

This agent handles the creative content generation for product descriptions
and titles. It uses brand context from RAG to ensure brand-consistent messaging.

NOTE: SEO generation is handled by SEOAgent for all tiers.
"""

from typing import List, Tuple

from ..base import BaseAgent
from ..state import MissionState
from ..context import AgentContext, AgentPlan, AgentAction
from .prompts import (
    REWRITER_SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    TONE_PROMPTS,
    VALUE_DISCOVERY_PROMPT,
    BRAND_CONTEXT_INJECTION_TEMPLATE,
    LEARNED_PREFERENCES_TEMPLATE,
    LOCALE_PERSONA_TEMPLATE,
    COMPLIANCE_FEEDBACK_TEMPLATE,
)
from src.main.config.configs import LOCALE_PERSONA_MAP
from src.main.logging.logger import get_logger

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
    """
    
    role_name = "Rewriter"
    default_tool = "llm.generate_text"
    
    # NOTE: requires_llm_reasoning = False (default)
    # Reasoning phase uses deterministic plan - NO LLM call

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
        """
        actions = []
        
        # Build prompts with brand context and learned rules
        system_prompt = self._build_system_prompt(state, context)
        user_prompt = self._build_user_prompt(state, context)
        
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
                    input_params={"prompt_len": len(user_prompt)},
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
                    input_params={"prompt_len": len(user_prompt) if user_prompt else 0},
                )
            )
            state.set_error(f"Content generation failed: {str(e)}")
        
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
    ) -> str:
        """Build system prompt with brand context and locale persona."""
        # Start with base system prompt
        prompt_parts = [REWRITER_SYSTEM_PROMPT]
        
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
    ) -> str:
        """Build user prompt with product data."""
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
            from src.main.utils.llm_parser import parse_llm_json
            
            parsed = parse_llm_json(result)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:
            logger.warning("[Rewriter] Failed to parse LLM result: %s", e)
        
        # Fallback: return raw content as description
        return {"description": result}


# Backward compatibility alias
CopywriterAgent = RewriterAgent

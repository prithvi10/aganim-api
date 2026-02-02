"""
ComplianceAgent - Checks content for regulatory compliance issues.

This agent scans generated content for potential compliance violations
using regex patterns for quick pre-filtering and LLM-as-judge for
nuanced analysis.
"""

import re
from typing import List, Tuple

from ..base import BaseAgent
from ..state import MissionState
from ..context import AgentContext, AgentPlan, AgentAction
from .prompts import (
    SYSTEM_PROMPT,
    CHECK_PROMPT_TEMPLATE,
    REGEX_FLAGS_SECTION_TEMPLATE,
    EMPTY_FLAGS_SECTION,
)
from .patterns import FDA_PATTERNS, FTC_PATTERNS, get_pattern_category
from .schemas import ComplianceCheck
from src.main.logging.logger import get_logger

logger = get_logger(__name__)


class ComplianceAgent(BaseAgent):
    """
    Agent for compliance checking (FDA, FTC, etc.).
    
    Uses:
    - Regex patterns for quick pre-filtering (Perception) - NO LLM call
    - Deterministic planning (Reasoning)
    - LLM-as-judge for nuanced checks (Action) - SINGLE LLM CALL
    
    This agent helps ensure product content doesn't violate
    regulatory guidelines before publication.
    """
    
    role_name = "Compliance"
    default_tool = "llm.generate_structured"
    
    # NOTE: requires_llm_reasoning = False (default)

    # -------------------------------------------------------------------------
    # PERCEPTION: Quick regex scan (NO LLM call)
    # -------------------------------------------------------------------------
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """
        Perform quick regex scan for obvious violations.
        
        This catches clear violations without needing an LLM call,
        speeding up the compliance check and reducing costs.
        """
        draft = state.draft_content or ""
        regex_flags = []
        
        # Check FDA patterns
        for pattern in FDA_PATTERNS:
            matches = re.findall(pattern, draft, re.IGNORECASE)
            if matches:
                regex_flags.append(
                    f"Potential FDA violation: found '{matches[0]}' "
                    f"(pattern: {pattern})"
                )
        
        # Check FTC patterns
        for pattern in FTC_PATTERNS:
            matches = re.findall(pattern, draft, re.IGNORECASE)
            if matches:
                regex_flags.append(
                    f"Potential FTC violation: found '{matches[0]}' "
                    f"(pattern: {pattern})"
                )
        
        context.external_data["regex_flags"] = regex_flags
        context.external_data["regex_check_done"] = True
        
        if regex_flags:
            logger.info(
                "[Compliance] Regex pre-scan found %d potential issues shop=%s",
                len(regex_flags),
                self.shop_id,
            )
        
        return context

    # NOTE: Uses default deterministic plan - NO LLM call in reasoning

    # -------------------------------------------------------------------------
    # ACTION: LLM-as-judge compliance check (SINGLE LLM CALL)
    # -------------------------------------------------------------------------
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Perform LLM-based compliance check.
        
        This is the ONLY LLM call for this agent.
        The LLM acts as a "judge" to catch nuanced violations
        that regex patterns might miss.
        """
        actions = []
        
        draft_content = state.draft_content or ""
        regex_flags = context.external_data.get("regex_flags", [])
        
        # If no content to check, skip
        if not draft_content.strip():
            state.compliance_flags = []
            actions.append(
                AgentAction.success_action(
                    tool_name="skip",
                    output="No content to check",
                    input_params={},
                )
            )
            return actions, state
        
        # Build prompt for LLM judge
        prompt = self._build_check_prompt(draft_content, regex_flags)
        
        try:
            # === THE ONLY LLM CALL FOR THIS AGENT ===
            check = await self.services.llm.generate_structured(
                prompt=prompt,
                response_format=ComplianceCheck,
                system_prompt=SYSTEM_PROMPT,
                model="gpt-4o-mini",
            )
            
            actions.append(
                AgentAction.success_action(
                    tool_name="llm.generate_structured",
                    output=check.model_dump(),
                    input_params={"response_format": "ComplianceCheck"},
                )
            )
            
            # Combine regex and LLM findings (deduplicate)
            all_flags = list(set(regex_flags + check.flags))
            state.compliance_flags = all_flags
            
            # Update status if issues found
            if check.has_violations or all_flags:
                state.status = "COMPLIANCE_REVIEW"
                logger.warning(
                    "[Compliance] Issues found shop=%s severity=%s flags=%d",
                    self.shop_id,
                    check.severity,
                    len(all_flags),
                )
            else:
                logger.info(
                    "[Compliance] Check passed shop=%s",
                    self.shop_id,
                )
            
        except Exception as e:
            actions.append(
                AgentAction.failure_action(
                    tool_name="llm.generate_structured",
                    error=str(e),
                    input_params={"response_format": "ComplianceCheck"},
                )
            )
            logger.error(
                "[Compliance] Check failed shop=%s err=%s",
                self.shop_id,
                e,
            )
            # Fall back to regex-only flags
            state.compliance_flags = regex_flags
            if regex_flags:
                state.status = "COMPLIANCE_REVIEW"
        
        return actions, state

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------
    def _build_check_prompt(
        self,
        content: str,
        regex_flags: List[str],
    ) -> str:
        """Build prompt for compliance check."""
        # Build flags section
        if regex_flags:
            flags_text = "\n".join(f"- {f}" for f in regex_flags)
            flags_section = REGEX_FLAGS_SECTION_TEMPLATE.format(flags=flags_text)
        else:
            flags_section = EMPTY_FLAGS_SECTION
        
        # Truncate content if too long
        max_content_length = 4000
        if len(content) > max_content_length:
            content = content[:max_content_length] + "..."
        
        return CHECK_PROMPT_TEMPLATE.format(
            content=content,
            flags_section=flags_section,
        )

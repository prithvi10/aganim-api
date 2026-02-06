"""
Agent context dataclasses for the agentic loop.

These dataclasses are used internally by agents during the
Perception → Reasoning → Action → Feedback cycle.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class AgentContext:
    """
    Context gathered during the PERCEPTION phase.
    
    This holds all the information an agent has collected about its
    environment before reasoning about what to do.
    
    Attributes:
        raw_input: The original product data from MissionState
        brand_context: Relevant brand context chunks from RAG
        learned_rules: Past corrections/preferences from memory
        external_data: Data from external services (SERP, APIs, etc.)
    """
    
    raw_input: Dict[str, Any]
    brand_context: List[Dict] = field(default_factory=list)
    learned_rules: List[Dict] = field(default_factory=list)
    external_data: Dict[str, Any] = field(default_factory=dict)

    def get_product_title(self) -> str:
        """Extract product title from raw input."""
        return str(
            self.raw_input.get("title")
            or self.raw_input.get("product_name")
            or ""
        ).strip()

    def get_product_description(self) -> str:
        """Extract product description from raw input."""
        return str(
            self.raw_input.get("description")
            or self.raw_input.get("japanese_description")
            or ""
        ).strip()

    def get_category(self) -> str:
        """Extract product category from raw input."""
        return str(
            self.raw_input.get("category")
            or self.raw_input.get("productType")
            or "General"
        ).strip()

    def get_brand_context_text(self) -> str:
        """Get brand context as a formatted string for prompts."""
        if not self.brand_context:
            return ""
        
        chunks = []
        for ctx in self.brand_context:
            content = ctx.get("content", "")
            if content:
                chunks.append(content)
        
        return "\n\n".join(chunks)

    def get_learned_rules_text(self) -> str:
        """Get learned rules as a formatted string for prompts."""
        if not self.learned_rules:
            return ""
        
        rules = []
        for rule in self.learned_rules:
            rule_text = rule.get("rule", rule.get("correction", ""))
            if rule_text:
                rules.append(f"- {rule_text}")
        
        return "\n".join(rules)


@dataclass
class AgentPlan:
    """
    Plan created during the REASONING phase.
    
    This represents the agent's decision about what actions to take,
    created either deterministically or via LLM reasoning.
    
    Attributes:
        steps: List of step names to execute
        selected_tools: Tools/services to use
        confidence: Agent's confidence in this plan (0.0-1.0)
        reasoning: Explanation of why this plan was chosen
    """
    
    steps: List[str]
    selected_tools: List[str]
    confidence: float
    reasoning: str

    def __post_init__(self):
        """Validate confidence is in range."""
        if not 0.0 <= self.confidence <= 1.0:
            self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class AgentAction:
    """
    Result of an action execution during the ACTION phase.
    
    Records what tool was called, what parameters were used,
    and whether it succeeded or failed.
    
    Attributes:
        tool_name: Name of the service/tool called
        input_params: Parameters passed to the tool
        output: Result from the tool (any type)
        success: Whether the action succeeded
        error: Error message if action failed
    """
    
    tool_name: str
    input_params: Dict[str, Any]
    output: Any
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "tool_name": self.tool_name,
            "input_params": self.input_params,
            "output": str(self.output)[:200] if self.output else None,  # Truncate for logging
            "success": self.success,
            "error": self.error,
        }

    @classmethod
    def success_action(
        cls,
        tool_name: str,
        output: Any,
        input_params: Optional[Dict[str, Any]] = None,
    ) -> "AgentAction":
        """Create a successful action result."""
        return cls(
            tool_name=tool_name,
            input_params=input_params or {},
            output=output,
            success=True,
            error=None,
        )

    @classmethod
    def failure_action(
        cls,
        tool_name: str,
        error: str,
        input_params: Optional[Dict[str, Any]] = None,
    ) -> "AgentAction":
        """Create a failed action result."""
        return cls(
            tool_name=tool_name,
            input_params=input_params or {},
            output=None,
            success=False,
            error=error,
        )

"""
LLM usage tracking data classes.

These are pure data containers with no external dependencies.
"""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class LLMUsage:
    """Token usage from an LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    model: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
        }


@dataclass
class AccumulatedUsage:
    """Accumulated token usage across multiple LLM calls."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    models_used: list = field(default_factory=list)

    def add(self, usage: LLMUsage) -> None:
        """Add usage from a single LLM call."""
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.reasoning_tokens += usage.reasoning_tokens
        self.total_tokens += usage.total_tokens
        self.call_count += 1
        if usage.model and usage.model not in self.models_used:
            self.models_used.append(usage.model)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
            "models_used": self.models_used,
        }

    def reset(self) -> None:
        """Reset accumulated usage."""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.total_tokens = 0
        self.call_count = 0
        self.models_used = []

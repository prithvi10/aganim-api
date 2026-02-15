"""
Rewriter Agent - Generates optimized product copy using RAG and LLM.
"""

from .agent import RewriterAgent
from .schemas import RewriterOutput

# Backward compatibility aliases
CopywriterAgent = RewriterAgent
CopywriterOutput = RewriterOutput

__all__ = ["RewriterAgent", "RewriterOutput", "CopywriterAgent", "CopywriterOutput"]

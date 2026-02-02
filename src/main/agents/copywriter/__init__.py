"""
Copywriter Agent - Generates optimized product copy using RAG and LLM.
"""

from .agent import CopywriterAgent
from .schemas import CopywriterOutput

__all__ = ["CopywriterAgent", "CopywriterOutput"]

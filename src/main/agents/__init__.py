"""
Agents Layer - Multi-Agent System for product content optimization.

Each agent follows the standard agentic loop:
1. PERCEPTION  - Gather context from environment (state, RAG, external APIs)
2. REASONING   - Analyze context and plan actions (deterministic OR LLM-based)
3. ACTION      - Execute tools/services to produce output
4. FEEDBACK    - Learn from outcomes for future improvement

Directory Structure:
    agents/
    ├── __init__.py          # This file - main exports
    ├── state.py             # MissionState (shared)
    ├── context.py           # AgentContext, AgentPlan, AgentAction (shared)
    ├── base.py              # BaseAgent ABC (shared)
    ├── memory.py            # AgentMemoryService (shared)
    ├── orchestrator.py      # MissionControl (shared)
    │
    ├── copywriter/          # Copywriter Agent (title + description)
    │   ├── agent.py
    │   ├── prompts.py
    │   └── schemas.py
    │
    ├── marketing/           # Marketing Agent (SEO + CTR + SERP + social hooks)
    │   ├── agent.py
    │   ├── prompts.py
    │   ├── schemas.py
    │   └── holidays.py
    │
    ├── price_scout/         # PriceScout Agent (pricing analysis)
    │   ├── agent.py
    │   ├── prompts.py
    │   └── schemas.py
    │
    └── compliance/          # Compliance Agent (regulatory checks)
        ├── agent.py
        ├── prompts.py
        ├── patterns.py
        └── schemas.py
"""

# Shared components
from .state import MissionState
from .context import AgentContext, AgentPlan, AgentAction
from .base import BaseAgent
from .memory import AgentMemoryService
from .orchestrator import MissionControl, run_mission

# Agent submodules (each is self-contained)
from .copywriter import CopywriterAgent, CopywriterOutput
from .marketing import (
    MarketingAgent,
    MarketingOutput,
    SEOInsights,
    SEORecommendations,
    CTRCheck,
    SerpCompetitor,
    SocialHook,
)
from .price_scout import PriceScoutAgent, PricingAnalysis
from .compliance import ComplianceAgent, ComplianceCheck

__all__ = [
    # Shared
    "MissionState",
    "AgentContext",
    "AgentPlan",
    "AgentAction",
    "BaseAgent",
    "AgentMemoryService",
    "MissionControl",
    "run_mission",
    # Agents
    "CopywriterAgent",
    "CopywriterOutput",
    "MarketingAgent",
    "MarketingOutput",
    "SEOInsights",
    "SEORecommendations",
    "CTRCheck",
    "SerpCompetitor",
    "SocialHook",
    "PriceScoutAgent",
    "PricingAnalysis",
    "ComplianceAgent",
    "ComplianceCheck",
]

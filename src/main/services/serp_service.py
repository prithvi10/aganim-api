# Backward-compat shim — canonical location: src/agentic_core/tools/serp_service.py
from src.agentic_core.tools.serp_service import (  # noqa: F401
    SerpService,
    SerpResult,
    ShoppingResult,
    fetch_top_results,
)

import src.agentic_core.tools.serp_service as _canonical_module


def __getattr__(name):
    return getattr(_canonical_module, name)

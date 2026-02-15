# Backward-compat shim — canonical location: src/agentic_core/tools/meta_service.py
from src.agentic_core.tools.meta_service import (  # noqa: F401
    MetaService,
    META_GRAPH_API,
)

import src.agentic_core.tools.meta_service as _canonical_module


def __getattr__(name):
    return getattr(_canonical_module, name)

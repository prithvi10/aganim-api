# Backward-compat shim — canonical location: src/agentic_core/rag/rag_service.py
#
# Re-exports RAGService and get_brand_context from the canonical location.
# Also uses __getattr__ for any other attribute access.

from src.agentic_core.rag.rag_service import (  # noqa: F401
    RAGService,
    get_brand_context,
)

import src.agentic_core.rag.rag_service as _canonical_module


def __getattr__(name):
    return getattr(_canonical_module, name)

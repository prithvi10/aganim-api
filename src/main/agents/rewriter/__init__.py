# Backward-compat shim — canonical location: src/ecommerce/agents/rewriter/
from src.ecommerce.agents.rewriter.agent import RewriterAgent  # noqa: F401
from src.ecommerce.agents.rewriter.schemas import RewriterOutput  # noqa: F401

import src.ecommerce.agents.rewriter as _canonical_module


def __getattr__(name):
    return getattr(_canonical_module, name)

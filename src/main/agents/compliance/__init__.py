# Backward-compat shim — canonical location: src/ecommerce/agents/compliance/
from src.ecommerce.agents.compliance.agent import ComplianceAgent  # noqa: F401
from src.ecommerce.agents.compliance.schemas import ComplianceCheck  # noqa: F401

import src.ecommerce.agents.compliance as _canonical_module


def __getattr__(name):
    return getattr(_canonical_module, name)

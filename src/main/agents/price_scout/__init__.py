# Backward-compat shim — canonical location: src/ecommerce/agents/price_scout/
from src.ecommerce.agents.price_scout.agent import PriceScoutAgent  # noqa: F401
from src.ecommerce.agents.price_scout.schemas import PricingAnalysis  # noqa: F401

import src.ecommerce.agents.price_scout as _canonical_module


def __getattr__(name):
    return getattr(_canonical_module, name)

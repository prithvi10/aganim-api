# Backward-compat shim — canonical location: src/ecommerce/agents/marketing/
from src.ecommerce.agents.marketing.agent import MarketingAgent  # noqa: F401
from src.ecommerce.agents.marketing.schemas import (  # noqa: F401
    MarketingOutput,
    SocialHook,
    SeasonalCampaign,
)

import src.ecommerce.agents.marketing as _canonical_module


def __getattr__(name):
    return getattr(_canonical_module, name)

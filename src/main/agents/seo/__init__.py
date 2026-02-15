# Backward-compat shim — canonical location: src/ecommerce/agents/seo/
from src.ecommerce.agents.seo.agent import SEOAgent  # noqa: F401
from src.ecommerce.agents.seo.schemas import SEOInsights, CTRCheck, SerpCompetitor, SEOOutput  # noqa: F401

import src.ecommerce.agents.seo as _canonical_module


def __getattr__(name):
    return getattr(_canonical_module, name)

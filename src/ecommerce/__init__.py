"""
Ecommerce package - Shopify domain layer.

Call ``register_domain_agents()`` at app startup to populate the
generic MissionControl with Shopify-specific agents.
"""


def register_domain_agents():
    """Register Shopify domain agents with the generic MissionControl."""
    from src.agentic_core.agents.orchestrator import register_agents
    from src.ecommerce.agents.rewriter import RewriterAgent
    from src.ecommerce.agents.seo import SEOAgent
    from src.ecommerce.agents.marketing import MarketingAgent
    from src.ecommerce.agents.price_scout import PriceScoutAgent

    register_agents({
        "RewriterAgent": RewriterAgent,
        "SEOAgent": SEOAgent,
        "MarketingAgent": MarketingAgent,
        "PriceScoutAgent": PriceScoutAgent,
    })

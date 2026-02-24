"""
Central source of truth for plan feature entitlements.

Every plan-gating decision (backend and frontend) should derive from this dict.
The frontend receives it via the /api/admin/usage endpoint.
"""

from __future__ import annotations

PLAN_ENTITLEMENTS: dict[str, dict] = {
    "Free": {
        "duration": "1_week_lifetime",
        "product_limit": 10,
        "rewriter": True,
        "seo": True,
        "marketing": True,
        "price_scout": True,
        "missions": True,
        "mission_limit": 3,
        "mission_limit_type": "lifetime",
        "mission_agents": "full",
        "image_generation_limit": 5,
        "image_limit_type": "lifetime",
        "image_refinement_adhoc": True,
        "ad_image_generation": True,
        "social_post_preview": False,
        "autonomous": False,
        "publish": False,
        "apply_price": False,
        "meta_integration": False,
    },
    "Basic": {
        "product_limit": 50,
        "rewriter": True,
        "seo": False,
        "marketing": True,
        "price_scout": False,
        "missions": True,
        "mission_limit": 1,
        "mission_limit_type": "monthly",
        "mission_agents": "text_only",
        "image_generation_limit": 0,
        "image_limit_type": "monthly",
        "image_refinement_adhoc": False,
        "ad_image_generation": False,
        "social_post_preview": False,
        "autonomous": False,
        "publish": False,
        "apply_price": False,
        "meta_integration": False,
    },
    "Standard": {
        "product_limit": -1,
        "rewriter": True,
        "seo": True,
        "marketing": True,
        "price_scout": True,
        "missions": True,
        "mission_limit": 3,
        "mission_limit_type": "monthly",
        "mission_agents": "text_full",
        "image_generation_limit": 0,
        "image_limit_type": "monthly",
        "image_refinement_adhoc": False,
        "ad_image_generation": False,
        "social_post_preview": False,
        "autonomous": False,
        "publish": False,
        "apply_price": False,
        "meta_integration": False,
    },
    "Pro": {
        "product_limit": -1,
        "rewriter": True,
        "seo": True,
        "marketing": True,
        "price_scout": True,
        "missions": True,
        "mission_limit": -1,
        "mission_limit_type": "monthly",
        "mission_agents": "full",
        "image_generation_limit": 150,
        "image_limit_type": "monthly",
        "image_refinement_adhoc": True,
        "ad_image_generation": True,
        "social_post_preview": True,
        "autonomous": True,
        "publish": True,
        "apply_price": True,
        "meta_integration": True,
    },
}

# Feature -> minimum tier that unlocks it (used for UI badge labels)
_FEATURE_MIN_TIER: dict[str, str] = {
    "seo": "Standard",
    "price_scout": "Standard",
    "image_refinement_adhoc": "Pro",
    "ad_image_generation": "Pro",
    "social_post_preview": "Pro",
    "autonomous": "Pro",
    "publish": "Pro",
    "apply_price": "Pro",
    "meta_integration": "Pro",
}


def get_entitlements(plan_name: str) -> dict:
    """Return the entitlements dict for a plan, defaulting to Free."""
    return dict(PLAN_ENTITLEMENTS.get(plan_name, PLAN_ENTITLEMENTS["Free"]))


def get_required_tier(feature: str) -> str | None:
    """Return the minimum tier name that unlocks *feature*, or None if all tiers have it."""
    return _FEATURE_MIN_TIER.get(feature)

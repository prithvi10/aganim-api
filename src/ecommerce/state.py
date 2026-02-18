"""
ShopifyMissionState - Shopify-specific extension of GenericMissionState.

This adds all the e-commerce / content-marketing fields that agents populate
during a Shopify product-optimisation mission.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session

from src.agentic_core.agents.state import GenericMissionState


@dataclass
class ShopifyMissionState(GenericMissionState):
    """
    Shopify-specific mission state extending GenericMissionState.

    Adds fields for product content, SEO, pricing, social media hooks,
    compliance, localisation, and usage tracking.

    Backward-compatible: the old ``MissionState`` name is aliased below
    so all existing code keeps working.

    Constructor uses legacy field names (product_id, shop_id, plan_tier)
    inherited from GenericMissionState.  Generic aliases (resource_id,
    tenant_id, tier) are available as @property accessors.
    """

    # Evolving artifacts (populated by agents)
    draft_content: Optional[str] = None
    draft_title: Optional[str] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    pricing_analysis: Optional[Dict[str, Any]] = None
    compliance_flags: List[str] = field(default_factory=list)
    discovered_values: List[Dict[str, Any]] = field(default_factory=list)

    # Marketing agent artifacts
    seo_alt_text: Optional[str] = None
    seo_insights: Optional[Dict[str, Any]] = None
    seo_recommendations: Optional[Dict[str, Any]] = None
    ctr_check: Optional[Dict[str, Any]] = None
    serp_insights: Optional[List[Dict[str, Any]]] = None
    social_hooks: Optional[List[Dict[str, Any]]] = None
    seasonal_campaign: Optional[Dict[str, Any]] = None

    # Visual agent artifacts (Pro tier)
    visual_assets: Optional[Dict[str, Any]] = None
    visual_progress: Optional[Dict[str, Any]] = None

    # Content hero agent artifacts (blog/collection hero banners)
    content_hero_assets: Optional[Dict[str, Any]] = None

    # Localisation
    target_locale: Optional[str] = None
    source_locale: Optional[str] = None

    # Token usage tracking for fair_use integration
    accumulated_usage: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert state to a JSON-serializable dictionary.

        Preserves all legacy key names so the frontend and database
        persistence continue to work unchanged.
        """
        d = self._generic_dict()
        # Shopify-specific fields
        d["draft_content"] = self.draft_content
        d["draft_title"] = self.draft_title
        d["seo_title"] = self.seo_title
        d["seo_description"] = self.seo_description
        d["pricing_analysis"] = self.pricing_analysis
        d["compliance_flags"] = self.compliance_flags
        d["discovered_values"] = self.discovered_values
        # Marketing agent artifacts
        d["seo_alt_text"] = self.seo_alt_text
        d["seo_insights"] = self.seo_insights
        d["seo_recommendations"] = self.seo_recommendations
        d["ctr_check"] = self.ctr_check
        d["serp_insights"] = self.serp_insights
        d["social_hooks"] = self.social_hooks
        d["seasonal_campaign"] = self.seasonal_campaign
        # Visual agent artifacts (Pro tier)
        d["visual_assets"] = self.visual_assets
        d["visual_progress"] = self.visual_progress
        # Content hero
        d["content_hero_assets"] = self.content_hero_assets
        # Locale & usage
        d["target_locale"] = self.target_locale
        d["source_locale"] = self.source_locale
        d["accumulated_usage"] = self.accumulated_usage
        return d

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        db: Optional[Session] = None,
    ) -> "ShopifyMissionState":
        """
        Create a ShopifyMissionState from a dictionary.

        Accepts both legacy key names (product_id, shop_id, plan_tier) and
        the new generic names (resource_id, tenant_id, tier).
        """
        return cls(
            # Generic fields -- accept both legacy and new keys
            shop_id=data.get("shop_id", data.get("tenant_id", "")),
            product_id=data.get("product_id", data.get("resource_id", "")),
            plan_tier=data.get("plan_tier", data.get("tier", "Free")),
            raw_input=data.get("raw_input", {}),
            db=db,
            logs=data.get("logs", []),
            status=data.get("status", "PENDING"),
            error_message=data.get("error_message"),
            current_agent_index=data.get("current_agent_index", 0),
            skipped_agents=data.get("skipped_agents", []),
            agent_outputs=data.get("agent_outputs", {}),
            regeneration_feedback=data.get("regeneration_feedback"),
            workflow_agents=data.get("workflow_agents", []),
            workflow_config=data.get("workflow_config", []),
            autonomous=data.get("autonomous", False),
            mission_id=data.get("mission_id"),
            # Shopify-specific fields
            draft_content=data.get("draft_content"),
            draft_title=data.get("draft_title"),
            seo_title=data.get("seo_title"),
            seo_description=data.get("seo_description"),
            pricing_analysis=data.get("pricing_analysis"),
            compliance_flags=data.get("compliance_flags", []),
            discovered_values=data.get("discovered_values", []),
            seo_alt_text=data.get("seo_alt_text"),
            seo_insights=data.get("seo_insights"),
            seo_recommendations=data.get("seo_recommendations"),
            ctr_check=data.get("ctr_check"),
            serp_insights=data.get("serp_insights"),
            social_hooks=data.get("social_hooks"),
            seasonal_campaign=data.get("seasonal_campaign"),
            visual_assets=data.get("visual_assets"),
            visual_progress=data.get("visual_progress"),
            content_hero_assets=data.get("content_hero_assets"),
            target_locale=data.get("target_locale"),
            source_locale=data.get("source_locale"),
            accumulated_usage=data.get("accumulated_usage"),
        )


# Backward-compat alias: most of the codebase uses ``MissionState``
MissionState = ShopifyMissionState

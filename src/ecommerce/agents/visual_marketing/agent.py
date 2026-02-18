"""
VisualMarketingAgent -- Marketing ad and hero banner generation.

Pipeline:
3. Marketing Ad with Typography (Ideogram 3.0 via fal.ai)
4. Hero Banner Outpainting (SD 3.5 via fal.ai)

Reads the refined product image from ``state.visual_assets["refined_url"]``
(set by ImageRefinementAgent earlier in the pipeline) or falls back to
``context.external_data["image_url"]`` for standalone use.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from src.agentic_core.agents.base import BaseAgent
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction
from src.ecommerce.state import ShopifyMissionState as MissionState
from src.ecommerce.agents.visual.prompts import build_hero_prompt
from src.shared.logging.logger import get_logger

if TYPE_CHECKING:
    from src.agentic_core.registry import ServiceRegistry

logger = get_logger(__name__)


class VisualMarketingAgent(BaseAgent):
    """
    Agent for marketing ad and hero banner image generation.

    Consumes:
        - Refined product image URL from ``state.visual_assets["refined_url"]``
          or product image URL from ``state.raw_input["image_url"]``
        - Social hook text from ``state.social_hooks`` or ``raw_input``
        - Brand Soul context from RAG perception

    Produces:
        - ``state.visual_assets["ad_url"]`` and ``state.visual_assets["hero_url"]``
        - ``state.visual_progress``: dict with phase/pct/label for SSE

    LLM Calls: 0 (all generation via fal.ai image models)
    """

    role_name = "VisualMarketing"
    requires_llm_reasoning = False
    default_tool = "visual_marketing.generate"

    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        raw = state.raw_input or {}

        # Prefer refined image from earlier pipeline step
        existing_assets = getattr(state, "visual_assets", None) or {}
        refined_url = existing_assets.get("refined_url", "")
        fallback_url = (
            raw.get("image_url")
            or raw.get("product_image_url")
            or raw.get("image_src")
            or ""
        )
        context.external_data["image_url"] = refined_url or fallback_url

        brand_soul = ""
        if context.strategic_intelligence:
            brand_soul = str(context.strategic_intelligence)[:600]
        elif raw.get("brand_context"):
            brand_soul = str(raw["brand_context"])[:600]
        context.external_data["brand_soul"] = brand_soul

        # Social hook text for ad typography
        hooks = getattr(state, "social_hooks", None) or []
        first_hook = ""
        if hooks:
            if isinstance(hooks[0], dict):
                first_hook = hooks[0].get("caption", hooks[0].get("text", ""))
            elif hasattr(hooks[0], "caption"):
                first_hook = hooks[0].caption
        context.external_data["hook_text"] = first_hook or raw.get("hook_text", "")
        context.external_data["product_name"] = raw.get(
            "product_name", raw.get("title", "")
        )
        context.external_data["brand_name"] = raw.get("brand_name", "")

        return context

    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        from src.ecommerce.services.visual_service import (
            VisualService,
            ImageURLValidationError,
        )
        from src.ecommerce.services.r2_storage_service import R2StorageService

        actions: List[AgentAction] = []
        image_url = context.external_data.get("image_url", "")

        if not image_url:
            state.add_log("VisualMarketing: Skipped -- no image URL available")
            actions.append(AgentAction(
                tool_name="visual_marketing.generate",
                input_params={"reason": "no_image_url"},
                output={},
                success=False,
                error="No product/refined image URL available",
            ))
            return actions, state

        visual_svc = VisualService()
        r2_svc = R2StorageService()
        mission_id = state.mission_id or "unknown"

        def _progress(phase: str, pct: int, label: str):
            state.visual_progress = {"phase": phase, "pct": pct, "label": label}
            state.add_log(f"VisualMarketing: [{pct}%] {label}")

        brand_soul = context.external_data.get("brand_soul", "")
        hook_text = context.external_data.get("hook_text", "")
        brand_name = context.external_data.get("brand_name", "")
        hero_prompt = build_hero_prompt(brand_soul=brand_soul)

        # Initialise or extend visual_assets dict
        visual_assets: Dict[str, Optional[str]] = dict(
            getattr(state, "visual_assets", None) or {}
        )
        visual_assets.setdefault("original_image_url", image_url)
        visual_assets.setdefault("ad_url", None)
        visual_assets.setdefault("hero_url", None)
        state.visual_assets = visual_assets

        try:
            import httpx

            # --- Marketing Ad ---
            if hook_text:
                ad_url = await visual_svc.generate_ad(
                    refined_image_url=image_url,
                    hook_text=hook_text,
                    brand_name=brand_name,
                    progress=_progress,
                )
                visual_assets["ad_url"] = ad_url

                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(ad_url)
                    resp.raise_for_status()
                    ad_bytes = resp.content

                ad_key = R2StorageService.build_key(state.shop_id, mission_id, "ad")
                ad_r2_url = await r2_svc.upload_asset(ad_bytes, ad_key)
                visual_assets["ad_url"] = ad_r2_url
                state.visual_assets = visual_assets
            else:
                _progress("ad_generation", 70, "Ad generation skipped (no hook text)")
                state.add_log(
                    "VisualMarketing: Ad skipped -- no social hook text available"
                )

            # --- Hero Banner ---
            hero_url = await visual_svc.expand_hero(
                refined_image_url=image_url,
                brand_prompt=hero_prompt,
                progress=_progress,
            )
            visual_assets["hero_url"] = hero_url

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(hero_url)
                resp.raise_for_status()
                hero_bytes = resp.content

            hero_key = R2StorageService.build_key(state.shop_id, mission_id, "hero")
            hero_r2_url = await r2_svc.upload_asset(hero_bytes, hero_key)
            visual_assets["hero_url"] = hero_r2_url
            state.visual_assets = visual_assets

            _progress("complete", 100, "Visual marketing complete")

            actions.append(AgentAction(
                tool_name="visual_marketing.generate",
                input_params={"image_url": image_url},
                output=visual_assets,
                success=True,
            ))

            logger.info(
                "[VisualMarketingAgent] complete shop=%s ad=%s hero=%s",
                state.shop_id,
                bool(visual_assets.get("ad_url")),
                bool(visual_assets.get("hero_url")),
            )

        except Exception as e:
            logger.exception(
                "[VisualMarketingAgent] pipeline failed shop=%s err=%s",
                state.shop_id, str(e),
            )
            _progress("error", 0, f"Visual marketing error: {str(e)[:100]}")
            actions.append(AgentAction(
                tool_name="visual_marketing.generate",
                input_params={"image_url": image_url},
                output={},
                success=False,
                error=str(e),
            ))
            state.visual_assets = visual_assets

        return actions, state

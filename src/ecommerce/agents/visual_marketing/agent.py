"""
VisualMarketingAgent -- Marketing ad generation via Nano Banana.

Primary pipeline (when product image is available):
  Product image + prompt → fal-ai/nano-banana/edit → marketing ad

Legacy fallback (no product image):
  Ideogram 3.0 typography ad.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from src.agentic_core.agents.base import BaseAgent
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction
from src.ecommerce.state import ShopifyMissionState as MissionState
from src.shared.logging.logger import get_logger

if TYPE_CHECKING:
    from src.agentic_core.registry import ServiceRegistry

logger = get_logger(__name__)


class VisualMarketingAgent(BaseAgent):
    """
    Agent for marketing ad image generation.

    Consumes:
        - Product image URL from ``state.raw_input["image_url"]``
          or refined image from ``state.visual_assets["refined_url"]``
        - Product name from ``raw_input``
        - Brand Soul context from RAG perception (passed through, disabled by default)

    Produces:
        - ``state.visual_assets["ad_url"]``
        - ``state.visual_assets["refined_url"]``
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

        hooks = getattr(state, "social_hooks", None) or []
        first_hook = ""
        if hooks:
            if isinstance(hooks[0], dict):
                first_hook = (
                    hooks[0].get("overlay")
                    or hooks[0].get("caption", hooks[0].get("text", ""))
                )
            elif hasattr(hooks[0], "overlay"):
                first_hook = hooks[0].overlay or getattr(hooks[0], "caption", "")
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
            validate_image_url,
            ImageURLValidationError,
        )
        from src.ecommerce.services.r2_storage_service import R2StorageService
        from src.ecommerce.services.product_ad_generator import ProductAdGenerator

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

        try:
            image_url = validate_image_url(image_url, allow_r2=True)
        except ImageURLValidationError as e:
            msg = f"Image URL rejected: {e}"
            logger.warning("[VisualMarketingAgent] %s url=%s", msg, image_url)
            state.add_log(f"VisualMarketing: {msg}")
            actions.append(AgentAction(
                tool_name="visual_marketing.generate",
                input_params={"reason": "url_validation_failed", "image_url": image_url},
                output={},
                success=False,
                error=msg,
            ))
            return actions, state

        r2_svc = R2StorageService()
        mission_id = state.mission_id or "unknown"

        def _progress(phase: str, pct: int, label: str):
            state.visual_progress = {"phase": phase, "pct": pct, "label": label}
            state.add_log(f"VisualMarketing: [{pct}%] {label}")

        product_name = context.external_data.get("product_name", "")
        brand_soul = context.external_data.get("brand_soul", "")

        visual_assets: Dict[str, Optional[str]] = dict(
            getattr(state, "visual_assets", None) or {}
        )
        visual_assets.setdefault("original_image_url", image_url)
        visual_assets.setdefault("refined_url", None)
        visual_assets.setdefault("ad_url", None)
        state.visual_assets = visual_assets

        try:
            ad_gen = ProductAdGenerator()
            ad_bytes = await ad_gen.generate(
                image_url=image_url,
                product_name=product_name,
                brand_soul=brand_soul,
                use_brand_style=False,
                progress=_progress,
            )

            _progress("uploading", 92, "Uploading final marketing image...")
            ad_key = R2StorageService.build_key(state.shop_id, mission_id, "ad")
            ad_r2_url = await r2_svc.upload_asset(ad_bytes, ad_key)
            visual_assets["ad_url"] = ad_r2_url
            visual_assets["refined_url"] = ad_r2_url
            state.visual_assets = visual_assets

            _progress("complete", 100, "Visual marketing complete")

            actions.append(AgentAction(
                tool_name="visual_marketing.generate",
                input_params={"image_url": image_url},
                output=visual_assets,
                success=True,
            ))

            logger.info(
                "[VisualMarketingAgent] complete shop=%s ad=%s",
                state.shop_id,
                bool(visual_assets.get("ad_url")),
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

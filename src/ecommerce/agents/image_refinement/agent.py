"""
ImageRefinementAgent -- Product image cleanup and background refinement.

Pipeline:
1.  Product Isolation (rembg local or BiRefNet cloud fallback)
2.  Background Refinement (Flux 2.0 Pro Redux via fal.ai)

Text and object removal steps are intentionally omitted: the background
is regenerated from scratch by Flux Pro, so background text is already
eliminated.  Removing text from the product itself (labels, logos, brand
names) would damage the product image.

Only runs for Pro-tier users.  Produces a single refined product image
stored in Cloudflare R2.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from src.agentic_core.agents.base import BaseAgent
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction
from src.ecommerce.state import ShopifyMissionState as MissionState
from src.ecommerce.agents.visual.prompts import build_inpaint_prompt
from src.shared.logging.logger import get_logger

if TYPE_CHECKING:
    from src.agentic_core.registry import ServiceRegistry

logger = get_logger(__name__)


class ImageRefinementAgent(BaseAgent):
    """
    Agent for AI product photo cleanup and background refinement.

    Consumes:
        - Product image URL from ``state.raw_input["image_url"]``
        - Brand Soul context from RAG perception

    Produces:
        - ``state.visual_assets``: dict with refined_url + original_image_url
        - ``state.visual_progress``: dict with phase/pct/label for SSE

    LLM Calls: 0 (all generation via fal.ai image models)
    """

    role_name = "ImageRefinement"
    requires_llm_reasoning = False
    default_tool = "image_refinement.generate"

    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        raw = state.raw_input or {}

        image_url = (
            raw.get("image_url")
            or raw.get("product_image_url")
            or raw.get("image_src")
            or ""
        )
        context.external_data["image_url"] = image_url

        brand_soul = ""
        if context.strategic_intelligence:
            brand_soul = str(context.strategic_intelligence)[:600]
        elif raw.get("brand_context"):
            brand_soul = str(raw["brand_context"])[:600]
        context.external_data["brand_soul"] = brand_soul

        context.external_data["product_name"] = raw.get(
            "product_name", raw.get("title", "")
        )

        if not image_url:
            logger.warning(
                "[ImageRefinementAgent] No image_url in raw_input shop=%s",
                state.shop_id,
            )

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

        actions: List[AgentAction] = []
        image_url = context.external_data.get("image_url", "")

        if not image_url:
            state.add_log("ImageRefinement: Skipped -- no product image URL")
            actions.append(AgentAction(
                tool_name="image_refinement.generate",
                input_params={"reason": "no_image_url"},
                output={},
                success=False,
                error="No product image URL provided",
            ))
            return actions, state

        try:
            image_url = validate_image_url(image_url)
        except ImageURLValidationError as e:
            msg = f"Image URL rejected: {e}"
            logger.warning("[ImageRefinementAgent] %s url=%s", msg, image_url)
            state.add_log(f"ImageRefinement: {msg}")
            actions.append(AgentAction(
                tool_name="image_refinement.generate",
                input_params={"reason": "url_validation_failed", "image_url": image_url},
                output={},
                success=False,
                error=msg,
            ))
            return actions, state

        visual_svc = VisualService()
        r2_svc = R2StorageService()
        mission_id = state.mission_id or "unknown"

        def _progress(phase: str, pct: int, label: str):
            state.visual_progress = {"phase": phase, "pct": pct, "label": label}
            state.add_log(f"ImageRefinement: [{pct}%] {label}")

        brand_soul = context.external_data.get("brand_soul", "")
        inpaint_prompt = build_inpaint_prompt(brand_soul=brand_soul)

        visual_assets: Dict[str, Optional[str]] = {
            "original_image_url": image_url,
            "refined_url": None,
            "ad_url": None,
            "hero_url": None,
        }
        state.visual_assets = visual_assets

        try:
            # Step 1: Isolate product (background removal)
            masked_bytes = await visual_svc.isolate_product(
                image_url=image_url, progress=_progress,
            )

            # Upload isolated product to R2
            mask_key = R2StorageService.build_key(state.shop_id, mission_id, "masked")
            await r2_svc.upload_asset(masked_bytes, mask_key)

            # Step 2: Refine background
            refined_url = await visual_svc.refine_product(
                masked_image_bytes=masked_bytes,
                brand_prompt=inpaint_prompt,
                progress=_progress,
            )
            visual_assets["refined_url"] = refined_url

            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(refined_url)
                resp.raise_for_status()
                refined_bytes = resp.content

            refined_key = R2StorageService.build_key(state.shop_id, mission_id, "refined")
            refined_r2_url = await r2_svc.upload_asset(refined_bytes, refined_key)
            visual_assets["refined_url"] = refined_r2_url
            state.visual_assets = visual_assets

            _progress("complete", 100, "Image refinement complete")

            actions.append(AgentAction(
                tool_name="image_refinement.generate",
                input_params={"image_url": image_url},
                output=visual_assets,
                success=True,
            ))

            logger.info(
                "[ImageRefinementAgent] complete shop=%s refined=%s",
                state.shop_id, bool(visual_assets["refined_url"]),
            )

        except Exception as e:
            logger.exception(
                "[ImageRefinementAgent] pipeline failed shop=%s err=%s",
                state.shop_id, str(e),
            )
            _progress("error", 0, f"Image refinement error: {str(e)[:100]}")
            actions.append(AgentAction(
                tool_name="image_refinement.generate",
                input_params={"image_url": image_url},
                output={},
                success=False,
                error=str(e),
            ))
            state.visual_assets = visual_assets

        return actions, state

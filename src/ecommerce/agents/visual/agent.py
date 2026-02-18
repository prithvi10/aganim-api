"""
VisualAgent -- Pro-Visual autonomous image generation pipeline.

Extends BaseAgent to provide a full visual refinement workflow:
1. Product Isolation (rembg background removal)
2. Background Refinement (Flux 2.0 Pro via fal.ai, guided by Brand Soul)
3. Marketing Ad with Typography (Ideogram 3.0 via fal.ai)
4. Hero Banner Outpainting (SD 3.5 via fal.ai)

Only runs for Pro-tier users.  Assets are stored in Cloudflare R2 and
optionally pushed to the Shopify Media Library via autonomous publish.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.agentic_core.agents.base import BaseAgent
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction
from src.ecommerce.state import ShopifyMissionState as MissionState

from .prompts import build_inpaint_prompt, build_ad_prompt, build_hero_prompt
from .schemas import VisualAssets, VisualProgress
from src.shared.logging.logger import get_logger

if TYPE_CHECKING:
    from src.agentic_core.registry import ServiceRegistry

logger = get_logger(__name__)


class VisualAgent(BaseAgent):
    """
    Agent for autonomous visual asset generation (Pro tier only).

    Consumes:
        - Product image URL from ``state.raw_input["image_url"]``
        - Brand Soul context from RAG perception
        - Social hooks from ``state.social_hooks`` (populated by MarketingAgent)

    Produces:
        - ``state.visual_assets``: dict with refined_url, ad_url, hero_url
        - ``state.visual_progress``: dict with phase/pct/label for SSE

    LLM Calls: 0 (all generation is via fal.ai image models)
    """

    role_name = "Visual"
    requires_llm_reasoning = False
    default_tool = "visual.generate"

    # Autonomous publish handlers: template_id → method name
    PUBLISH_MAP: Dict[str, Callable] = {
        "visual/product-refine": "_publish_visual_assets",
    }

    # ------------------------------------------------------------------
    # PERCEPTION
    # ------------------------------------------------------------------

    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """
        Gather visual-specific context:
        - Product image URL
        - Brand Soul (for style-aware generation)
        - Social hooks (for ad typography)
        """
        raw = state.raw_input or {}

        # Extract product image URL
        image_url = (
            raw.get("image_url")
            or raw.get("product_image_url")
            or raw.get("image_src")
            or ""
        )
        context.external_data["image_url"] = image_url

        # Extract brand soul summary for prompt engineering
        brand_soul = ""
        if context.strategic_intelligence:
            brand_soul = str(context.strategic_intelligence)[:600]
        elif raw.get("brand_context"):
            brand_soul = str(raw["brand_context"])[:600]
        context.external_data["brand_soul"] = brand_soul

        # Extract social hooks for ad typography
        hooks = getattr(state, "social_hooks", None) or []
        first_hook = ""
        if hooks:
            if isinstance(hooks[0], dict):
                first_hook = hooks[0].get("caption", hooks[0].get("text", ""))
            elif hasattr(hooks[0], "caption"):
                first_hook = hooks[0].caption
        context.external_data["hook_text"] = first_hook or raw.get("hook_text", "")

        # Product and brand metadata
        context.external_data["product_name"] = raw.get("product_name", raw.get("title", ""))
        context.external_data["brand_name"] = raw.get("brand_name", "")

        if not image_url:
            logger.warning(
                "[VisualAgent] No image_url found in raw_input for shop=%s",
                state.shop_id,
            )

        return context

    # ------------------------------------------------------------------
    # ACTION
    # ------------------------------------------------------------------

    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """
        Execute the full visual pipeline:
        1. Isolate product (rembg)
        2. Refine background (Flux 2.0 Pro)
        3. Generate marketing ad (Ideogram 3.0)
        4. Expand hero banner (SD 3.5)
        5. Upload to R2
        """
        from src.ecommerce.services.visual_service import (
            VisualService,
            validate_image_url,
            ImageURLValidationError,
        )
        from src.ecommerce.services.r2_storage_service import R2StorageService

        actions: List[AgentAction] = []
        image_url = context.external_data.get("image_url", "")

        if not image_url:
            state.add_log("Visual: Skipped -- no product image URL available")
            action = AgentAction(
                tool_name="visual.generate",
                input_params={"reason": "no_image_url"},
                output={},
                success=False,
                error="No product image URL provided",
            )
            actions.append(action)
            return actions, state

        # ── SSRF prevention: validate image URL before sending to fal.ai ──
        try:
            image_url = validate_image_url(image_url)
        except ImageURLValidationError as e:
            msg = f"Image URL rejected: {e}"
            logger.warning("[VisualAgent] %s  url=%s", msg, image_url)
            state.add_log(f"Visual: {msg}")
            action = AgentAction(
                tool_name="visual.generate",
                input_params={"reason": "url_validation_failed", "image_url": image_url},
                output={},
                success=False,
                error=msg,
            )
            actions.append(action)
            return actions, state

        visual_svc = VisualService()
        r2_svc = R2StorageService()
        mission_id = state.mission_id or "unknown"

        # Build a progress callback that writes to state for SSE streaming
        def _progress(phase: str, pct: int, label: str):
            state.visual_progress = {
                "phase": phase,
                "pct": pct,
                "label": label,
            }
            state.add_log(f"Visual: [{pct}%] {label}")

        # Build prompts from Brand Soul (all prompt tuning is in prompts.py)
        brand_soul = context.external_data.get("brand_soul", "")
        product_name = context.external_data.get("product_name", "Product")
        brand_name = context.external_data.get("brand_name", "")
        hook_text = context.external_data.get("hook_text", "")

        inpaint_prompt = build_inpaint_prompt(brand_soul=brand_soul)
        hero_prompt = build_hero_prompt(brand_soul=brand_soul)

        visual_assets: Dict[str, Optional[str]] = {
            "original_image_url": image_url,
            "refined_url": None,
            "ad_url": None,
            "hero_url": None,
        }
        state.visual_assets = visual_assets

        try:
            # --- Step 1: Isolate product ---
            masked_bytes = await visual_svc.isolate_product(
                image_url=image_url,
                progress=_progress,
            )

            # --- Step 1b: Remove text overlays ---
            masked_bytes = await visual_svc.remove_text(
                image_bytes=masked_bytes,
                progress=_progress,
            )

            # Upload cleaned image to R2 for reference
            mask_key = R2StorageService.build_key(
                state.shop_id, mission_id, "masked"
            )
            await r2_svc.upload_asset(masked_bytes, mask_key)

            # --- Step 2: Refine background ---
            refined_url = await visual_svc.refine_product(
                masked_image_bytes=masked_bytes,
                brand_prompt=inpaint_prompt,
                progress=_progress,
            )
            visual_assets["refined_url"] = refined_url

            # Download refined image and store in R2
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(refined_url)
                resp.raise_for_status()
                refined_bytes = resp.content

            refined_key = R2StorageService.build_key(
                state.shop_id, mission_id, "refined"
            )
            refined_r2_url = await r2_svc.upload_asset(refined_bytes, refined_key)
            visual_assets["refined_url"] = refined_r2_url
            state.visual_assets = visual_assets

            # --- Step 3: Marketing Ad ---
            if hook_text:
                ad_url = await visual_svc.generate_ad(
                    refined_image_url=refined_url,
                    hook_text=hook_text,
                    brand_name=brand_name,
                    progress=_progress,
                )
                visual_assets["ad_url"] = ad_url

                # Store ad in R2
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(ad_url)
                    resp.raise_for_status()
                    ad_bytes = resp.content

                ad_key = R2StorageService.build_key(
                    state.shop_id, mission_id, "ad"
                )
                ad_r2_url = await r2_svc.upload_asset(ad_bytes, ad_key)
                visual_assets["ad_url"] = ad_r2_url
                state.visual_assets = visual_assets
            else:
                _progress("ad_generation", 70, "Ad generation skipped (no hook text)")
                state.add_log("Visual: Ad generation skipped -- no social hook text available")

            # --- Step 4: Hero Banner ---
            hero_url = await visual_svc.expand_hero(
                refined_image_url=refined_url,
                brand_prompt=hero_prompt,
                progress=_progress,
            )
            visual_assets["hero_url"] = hero_url

            # Store hero in R2
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(hero_url)
                resp.raise_for_status()
                hero_bytes = resp.content

            hero_key = R2StorageService.build_key(
                state.shop_id, mission_id, "hero"
            )
            hero_r2_url = await r2_svc.upload_asset(hero_bytes, hero_key)
            visual_assets["hero_url"] = hero_r2_url
            state.visual_assets = visual_assets

            # --- Finalize ---
            _progress("complete", 100, "Visual pipeline complete")

            action = AgentAction(
                tool_name="visual.generate",
                input_params={"image_url": image_url},
                output=visual_assets,
                success=True,
            )
            actions.append(action)

            logger.info(
                "[VisualAgent] pipeline complete shop=%s refined=%s ad=%s hero=%s",
                state.shop_id,
                bool(visual_assets["refined_url"]),
                bool(visual_assets["ad_url"]),
                bool(visual_assets["hero_url"]),
            )

        except Exception as e:
            logger.exception(
                "[VisualAgent] pipeline failed shop=%s err=%s",
                state.shop_id, str(e),
            )
            _progress("error", 0, f"Visual pipeline error: {str(e)[:100]}")
            action = AgentAction(
                tool_name="visual.generate",
                input_params={"image_url": image_url},
                output={},
                success=False,
                error=str(e),
            )
            actions.append(action)
            # Store partial results
            state.visual_assets = visual_assets

        return actions, state

    # ------------------------------------------------------------------
    # AUTONOMOUS PUBLISH
    # ------------------------------------------------------------------

    async def _publish_visual_assets(self, state: MissionState, creds: dict) -> None:
        """
        Push generated visual assets to Shopify:
        1. Append refined image to the product gallery (non-destructive).
        2. Upload ad + hero to the Media Library.
        """
        from src.ecommerce.services.shopify_service import (
            upload_media_to_shopify,
            add_product_image,
        )

        assets = getattr(state, "visual_assets", None) or {}
        access_token = creds.get("access_token", "")

        if not access_token:
            state.add_log("Visual: Publish skipped -- missing Shopify credentials")
            return

        import httpx

        product_name = (state.raw_input or {}).get("product_name", "product")
        product_id = getattr(state, "product_id", "")

        # ── 1. Append refined image to product gallery ──
        refined_url = assets.get("refined_url")
        if refined_url and product_id:
            try:
                media_gid = await add_product_image(
                    shop_domain=state.shop_id,
                    access_token=access_token,
                    product_id=product_id,
                    image_url=refined_url,
                    alt_text=f"{product_name} - AI-refined product image",
                )
                state.add_log(f"Visual: Refined image added to product gallery ({media_gid})")
                logger.info(
                    "[VisualAgent] refined image appended to product %s shop=%s",
                    product_id, state.shop_id,
                )
            except Exception as e:
                state.add_log(f"Visual: Failed to add refined image to product: {str(e)[:100]}")
                logger.error(
                    "[VisualAgent] append refined to product failed shop=%s err=%s",
                    state.shop_id, str(e),
                )

        # ── 2. Upload ad + hero to Shopify Media Library ──
        for asset_type in ("ad", "hero"):
            url = assets.get(f"{asset_type}_url")
            if not url:
                continue

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    image_bytes = resp.content

                filename = f"{product_name}-{asset_type}.png"

                await upload_media_to_shopify(
                    shop_domain=state.shop_id,
                    access_token=access_token,
                    image_bytes=image_bytes,
                    filename=filename,
                    alt_text=f"{product_name} - {asset_type} visual",
                )

                state.add_log(f"Visual: Published {asset_type} to Shopify Media Library")
                logger.info(
                    "[VisualAgent] published %s to Shopify shop=%s",
                    asset_type, state.shop_id,
                )
            except Exception as e:
                state.add_log(f"Visual: Failed to publish {asset_type}: {str(e)[:100]}")
                logger.error(
                    "[VisualAgent] publish %s failed shop=%s err=%s",
                    asset_type, state.shop_id, str(e),
                )

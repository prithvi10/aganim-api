"""
ContentHeroAgent -- Art-directed hero image generation.

Two-step pipeline:
  1. LLM Art Director (gpt-4o-mini) analyzes product metadata and brand soul
     to produce a structured VisualBrief (surface, lighting, environment, palette).
  2. Style-specific Nano Banana prompt consumes the VisualBrief to generate a
     photorealistic hero banner.

Supports 4 image styles:
  - Informative: product name + logo baked into the scene
  - Minimalist: isolated product on clean surface
  - Attractive: product with contextual props and themed background
  - Seasonal: product with seasonal elements matching current season

Supports two generation modes:
  - Text-to-image (T2I): no product image needed
  - Image-to-image (img2img): blends a product reference image into the scene

LLM Calls: 1 (Art Director visual brief via gpt-4o-mini)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.agentic_core.agents.base import BaseAgent
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction
from src.ecommerce.state import ShopifyMissionState as MissionState
from src.shared.logging.logger import get_logger

if TYPE_CHECKING:
    from src.agentic_core.registry import ServiceRegistry

logger = get_logger(__name__)

HERO_ELIGIBLE_TEMPLATES = {
    "product/blog-post",
    "product/collection",
    "product/landing-hero",
}


class ContentHeroAgent(BaseAgent):
    """
    Agent for generating art-directed hero banners.

    Consumes:
        - Previous agent output from ``state.agent_outputs`` (blog/collection)
        - Brand Soul from strategic intelligence
        - Optional ``image_style`` from raw_input (default: "attractive")
        - Optional ``image_url`` from raw_input (product reference)
        - Optional ``logo_url`` from raw_input or shop record

    Produces:
        - ``state.content_hero_assets``: dict with hero_url, content_type,
          theme_context, image_style

    LLM Calls: 1 (Art Director)
    """

    role_name = "ContentHero"
    requires_llm_reasoning = False
    default_tool = "content_hero.generate"

    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        raw = state.raw_input or {}

        brand_soul = ""
        if context.strategic_intelligence:
            brand_soul = str(context.strategic_intelligence)[:300]
        elif raw.get("brand_context"):
            brand_soul = str(raw["brand_context"])[:300]
        context.external_data["brand_soul"] = brand_soul

        context.external_data["image_style"] = raw.get("image_style", "attractive")
        context.external_data["image_url"] = raw.get("image_url", "")
        context.external_data["logo_url"] = raw.get("logo_url", "")
        context.external_data["brand_name"] = raw.get("brand_name", "")
        context.external_data["product_name"] = raw.get("product_name", "")
        context.external_data["product_category"] = raw.get("category", "General")

        template_id = ""
        context_data: Dict[str, Any] = {}
        for _key, out in reversed(list((state.agent_outputs or {}).items())):
            if not isinstance(out, dict):
                continue
            tmpl = out.get("template_id")
            if tmpl == "product/blog-post":
                template_id = tmpl
                context_data = {
                    "subject": out.get("draft_title") or raw.get("topic", ""),
                    "category": raw.get("category", "General"),
                    "context": raw.get("context", ""),
                }
                if not context.external_data["product_name"]:
                    context.external_data["product_name"] = context_data["subject"]
                break
            elif tmpl == "product/collection":
                template_id = tmpl
                product_names = raw.get("product_names", [])
                if isinstance(product_names, str):
                    product_names = [n.strip() for n in product_names.split(",") if n.strip()]
                context_data = {
                    "collection_name": raw.get("collection_name", ""),
                    "description": raw.get("description", ""),
                    "product_names": product_names,
                }
                if not context.external_data["product_name"]:
                    context.external_data["product_name"] = context_data["collection_name"]
                break
            elif tmpl == "product/landing-hero":
                template_id = tmpl
                context_data = {
                    "subject": out.get("draft_title") or raw.get("subject_text", raw.get("title", "")),
                    "overlay_text": raw.get("overlay_text", ""),
                }
                if not context.external_data["product_name"]:
                    context.external_data["product_name"] = context_data["subject"]
                break

        context.external_data["template_id"] = template_id
        context.external_data["context_data"] = context_data

        return context

    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        from src.ecommerce.services.hero_image_generator import HeroImageGenerator
        from src.ecommerce.services.r2_storage_service import R2StorageService
        from src.ecommerce.services.art_director import (
            generate_visual_brief,
            ImageStyle,
            get_current_season,
            get_season_props,
        )
        from src.ecommerce.agents.visual.prompts import (
            build_styled_prompt,
            build_collection_hero_prompt,
            build_blog_hero_prompt,
            build_hero_section_prompt,
        )

        actions: List[AgentAction] = []
        template_id = context.external_data.get("template_id", "")
        context_data = context.external_data.get("context_data", {})
        brand_soul = context.external_data.get("brand_soul", "")
        image_style = context.external_data.get("image_style", "attractive")
        image_url = context.external_data.get("image_url", "")
        brand_name = context.external_data.get("brand_name", "")
        product_name = context.external_data.get("product_name", "")
        product_category = context.external_data.get("product_category", "General")

        if not template_id:
            state.add_log("ContentHero: Skipped -- no preceding blog/collection step found")
            actions.append(AgentAction(
                tool_name="content_hero.generate",
                input_params={"reason": "no_preceding_content"},
                output={},
                success=False,
                error="No preceding blog/collection agent output found",
            ))
            return actions, state

        hero_gen = HeroImageGenerator()
        r2_svc = R2StorageService()
        mission_id = state.mission_id or "unknown"

        def _progress(phase: str, pct: int, label: str):
            state.visual_progress = {"phase": phase, "pct": pct, "label": label}
            state.add_log(f"ContentHero: [{pct}%] {label}")

        # Determine content type for metadata
        if template_id == "product/blog-post":
            content_type = "blog"
            theme_context = context_data.get("subject", "")
        elif template_id == "product/collection":
            content_type = "collection"
            theme_context = context_data.get("collection_name", "")
        else:
            content_type = "hero"
            theme_context = context_data.get("subject", "")

        try:
            # ── Step 1: Art Director (LLM visual brief) ──────────────
            _progress("art_direction", 5, "Art Director analyzing product...")

            try:
                style_enum = ImageStyle(image_style)
            except ValueError:
                style_enum = ImageStyle.ATTRACTIVE

            llm_service = getattr(self.services, "llm", None)
            brief = await generate_visual_brief(
                product_name=product_name or theme_context,
                category=product_category,
                brand_soul=brand_soul,
                style=style_enum,
                llm_service=llm_service,
            )

            _progress("art_direction", 15, "Visual brief ready")
            state.add_log(
                f"ContentHero: VisualBrief surface={brief.surface_material} "
                f"lighting={brief.lighting_scheme[:50]}"
            )

            # ── Step 2: Build style-specific prompt ──────────────────
            season = ""
            season_props = ""
            if style_enum == ImageStyle.SEASONAL:
                season = get_current_season()
                season_props = get_season_props(season)

            hero_prompt = build_styled_prompt(
                style=image_style,
                brief=brief,
                product_name=product_name or theme_context,
                brand_name=brand_name,
                season=season,
                season_props=season_props,
            )

            # ── Step 3: Generate hero image ──────────────────────────
            if image_url:
                _progress("generating", 20, "Blending product into hero banner...")
                hero_bytes = await hero_gen.generate_from_image(
                    image_url=image_url,
                    prompt=hero_prompt,
                    progress=_progress,
                )
            else:
                _progress("generating", 20, "Generating hero banner...")
                hero_bytes = await hero_gen.generate(
                    prompt=hero_prompt,
                    progress=_progress,
                )

            # ── Step 4: Upload to R2 ─────────────────────────────────
            hero_key = R2StorageService.build_key(
                state.shop_id, mission_id, "content-hero",
            )
            r2_url = await r2_svc.upload_asset(hero_bytes, hero_key)

            state.content_hero_assets = {
                "content_type": content_type,
                "hero_url": r2_url,
                "theme_context": theme_context,
                "image_style": image_style,
            }

            _progress("complete", 100, "Content hero banner complete")

            actions.append(AgentAction(
                tool_name="content_hero.generate",
                input_params={
                    "template_id": template_id,
                    "image_style": image_style,
                    "has_product_image": bool(image_url),
                },
                output=state.content_hero_assets,
                success=True,
            ))

            logger.info(
                "[ContentHeroAgent] complete shop=%s type=%s style=%s img2img=%s hero=%s",
                state.shop_id, content_type, image_style, bool(image_url), bool(r2_url),
            )

        except Exception as e:
            logger.exception(
                "[ContentHeroAgent] failed shop=%s err=%s",
                state.shop_id, str(e),
            )
            _progress("error", 0, f"Content hero error: {str(e)[:100]}")
            actions.append(AgentAction(
                tool_name="content_hero.generate",
                input_params={"template_id": template_id},
                output={},
                success=False,
                error=str(e),
            ))

        return actions, state

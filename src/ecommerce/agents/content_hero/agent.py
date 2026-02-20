"""
ContentHeroAgent -- Hero image generation for blog and collection content.

Lightweight agent that runs after a RewriterAgent step (blog/collection/hero)
in the mission pipeline. Reads the preceding agent output to extract theme
context, then generates a 16:9 hero banner via HeroImageGenerator
(Nano Banana text-to-image).

LLM Calls: 0 (all generation via fal.ai image models)
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
    Agent for generating hero banners after blog/collection content generation.

    Consumes:
        - Previous agent output from ``state.agent_outputs`` (blog/collection)
        - Brand Soul from strategic intelligence

    Produces:
        - ``state.content_hero_assets``: dict with hero_url, content_type, theme_context

    LLM Calls: 0
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
                break
            elif tmpl == "product/landing-hero":
                template_id = tmpl
                context_data = {
                    "subject": out.get("draft_title") or raw.get("subject_text", raw.get("title", "")),
                    "overlay_text": raw.get("overlay_text", ""),
                }
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
        from src.ecommerce.agents.visual.prompts import (
            build_collection_hero_prompt,
            build_blog_hero_prompt,
            build_hero_section_prompt,
        )

        actions: List[AgentAction] = []
        template_id = context.external_data.get("template_id", "")
        context_data = context.external_data.get("context_data", {})
        brand_soul = context.external_data.get("brand_soul", "")

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

        if template_id == "product/blog-post":
            hero_prompt = build_blog_hero_prompt(
                subject=context_data.get("subject", ""),
                category=context_data.get("category", "General"),
                context=context_data.get("context", ""),
                brand_soul=brand_soul,
            )
            content_type = "blog"
            theme_context = context_data.get("subject", "")
        elif template_id == "product/collection":
            hero_prompt = build_collection_hero_prompt(
                collection_name=context_data.get("collection_name", ""),
                description=context_data.get("description", ""),
                product_names=context_data.get("product_names", []),
                brand_soul=brand_soul,
            )
            content_type = "collection"
            theme_context = context_data.get("collection_name", "")
        else:
            hero_prompt = build_hero_section_prompt(
                subject=context_data.get("subject", ""),
                overlay_text=context_data.get("overlay_text", ""),
                brand_soul=brand_soul,
            )
            content_type = "hero"
            theme_context = context_data.get("subject", "")

        try:
            hero_bytes = await hero_gen.generate(
                prompt=hero_prompt,
                progress=_progress,
            )

            hero_key = R2StorageService.build_key(
                state.shop_id, mission_id, "content-hero",
            )
            r2_url = await r2_svc.upload_asset(hero_bytes, hero_key)

            state.content_hero_assets = {
                "content_type": content_type,
                "hero_url": r2_url,
                "theme_context": theme_context,
            }

            _progress("complete", 100, "Content hero banner complete")

            actions.append(AgentAction(
                tool_name="content_hero.generate",
                input_params={"template_id": template_id},
                output=state.content_hero_assets,
                success=True,
            ))

            logger.info(
                "[ContentHeroAgent] complete shop=%s type=%s hero=%s",
                state.shop_id, content_type, bool(r2_url),
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

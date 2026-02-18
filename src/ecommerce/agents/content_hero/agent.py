"""
ContentHeroAgent -- Hero image generation for blog and collection content.

Lightweight agent that runs after a RewriterAgent step (blog/collection/hero)
in the mission pipeline. Reads the preceding agent output to extract theme
context, then generates a 16:9 hero banner via VisualService.expand_hero().

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
        - Product image URL from ``state.raw_input["image_url"]``
        - Brand Soul from strategic intelligence (truncated to ~120 chars)

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

        image_url = (
            raw.get("image_url")
            or raw.get("product_image_url")
            or raw.get("image_src")
            or ""
        )
        context.external_data["image_url"] = image_url

        short_soul = ""
        if context.strategic_intelligence:
            short_soul = str(context.strategic_intelligence)[:120]
        elif raw.get("brand_context"):
            short_soul = str(raw["brand_context"])[:120]
        context.external_data["short_soul"] = short_soul

        subject = ""
        context_text = ""
        for _key, out in reversed(list((state.agent_outputs or {}).items())):
            if not isinstance(out, dict):
                continue
            tmpl = out.get("template_id")
            if tmpl == "product/blog-post":
                subject = "Blog"
                context_text = out.get("draft_title") or raw.get("topic", "")
                break
            elif tmpl == "product/collection":
                subject = "Collection"
                context_text = raw.get("collection_name", "")
                break
            elif tmpl == "product/landing-hero":
                subject = "Hero section"
                context_text = out.get("draft_title") or raw.get("title", "")
                break

        context.external_data["subject"] = subject
        context.external_data["context_text"] = context_text

        return context

    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        from src.ecommerce.services.visual_service import VisualService
        from src.ecommerce.services.r2_storage_service import R2StorageService

        actions: List[AgentAction] = []
        image_url = context.external_data.get("image_url", "")
        subject = context.external_data.get("subject", "")
        context_text = context.external_data.get("context_text", "")
        short_soul = context.external_data.get("short_soul", "")

        if not image_url:
            state.add_log("ContentHero: Skipped -- no image URL available")
            actions.append(AgentAction(
                tool_name="content_hero.generate",
                input_params={"reason": "no_image_url"},
                output={},
                success=False,
                error="No product image URL available for hero generation",
            ))
            return actions, state

        if not subject:
            state.add_log("ContentHero: Skipped -- no preceding blog/collection step found")
            actions.append(AgentAction(
                tool_name="content_hero.generate",
                input_params={"reason": "no_preceding_content"},
                output={},
                success=False,
                error="No preceding blog/collection agent output found",
            ))
            return actions, state

        visual_svc = VisualService()
        r2_svc = R2StorageService()
        mission_id = state.mission_id or "unknown"

        def _progress(phase: str, pct: int, label: str):
            state.visual_progress = {"phase": phase, "pct": pct, "label": label}
            state.add_log(f"ContentHero: [{pct}%] {label}")

        hero_prompt = f"{subject} banner. Theme: {context_text}. Style: {short_soul}"

        try:
            import httpx

            hero_url = await visual_svc.expand_hero(
                refined_image_url=image_url,
                brand_prompt=hero_prompt,
                progress=_progress,
            )

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(hero_url)
                resp.raise_for_status()
                hero_bytes = resp.content

            hero_key = R2StorageService.build_key(
                state.shop_id, mission_id, "content-hero",
            )
            r2_url = await r2_svc.upload_asset(hero_bytes, hero_key)

            state.content_hero_assets = {
                "content_type": subject.lower(),
                "hero_url": r2_url,
                "theme_context": context_text,
            }

            _progress("complete", 100, "Content hero banner complete")

            actions.append(AgentAction(
                tool_name="content_hero.generate",
                input_params={"image_url": image_url, "subject": subject},
                output=state.content_hero_assets,
                success=True,
            ))

            logger.info(
                "[ContentHeroAgent] complete shop=%s type=%s hero=%s",
                state.shop_id, subject, bool(r2_url),
            )

        except Exception as e:
            logger.exception(
                "[ContentHeroAgent] failed shop=%s err=%s",
                state.shop_id, str(e),
            )
            _progress("error", 0, f"Content hero error: {str(e)[:100]}")
            actions.append(AgentAction(
                tool_name="content_hero.generate",
                input_params={"image_url": image_url, "subject": subject},
                output={},
                success=False,
                error=str(e),
            ))

        return actions, state

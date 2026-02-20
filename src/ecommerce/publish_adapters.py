"""
Shopify Publish Adapters - Implements PublishAdapter for pushing content to Shopify.

All Shopify API interactions for autonomous publishing live here so that
the agentic core (agents/, services/) stays domain-agnostic.

Agent handler methods delegate to these adapters via ServiceRegistry.publish_adapter.
"""

import json
from typing import Any, Dict, Optional, Tuple

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ShopifyPublishAdapter:
    """
    Concrete PublishAdapter for the Shopify platform.

    Wraps src.ecommerce.services.shopify_service calls behind the PublishAdapter
    protocol so that BaseAgent never imports shopify_service directly.
    """

    # ------------------------------------------------------------------
    # PublishAdapter protocol
    # ------------------------------------------------------------------

    async def get_credentials(self, db: Any, tenant_id: str) -> dict:
        """Load Shopify shop credentials (access_token, price_guardrails, meta creds)."""
        from src.ecommerce.services.shopify_service import get_shop_credentials

        if db is None:
            return {}
        return get_shop_credentials(db, tenant_id)

    async def publish(
        self,
        state: Any,
        template_id: str,
        handler_ref: Any,
        creds: dict,
    ) -> Tuple[bool, Optional[str]]:
        """
        Generic publish dispatch (not currently used — agents delegate to
        individual methods below).  Kept for protocol completeness.
        """
        raise NotImplementedError("Use individual publish methods instead")

    # ------------------------------------------------------------------
    # Rewriter publish handlers
    # ------------------------------------------------------------------

    async def publish_product_body(self, state: Any, creds: dict) -> None:
        """Push draft_content → Shopify descriptionHtml."""
        from src.ecommerce.services.shopify_service import update_product_body

        await update_product_body(
            shop_domain=state.shop_id,
            access_token=creds["access_token"],
            product_id=state.product_id,
            html=state.draft_content or "",
        )

    async def publish_faq_append(self, state: Any, creds: dict) -> None:
        """Convert FAQ JSON → HTML and append to product description."""
        from src.ecommerce.services.shopify_service import (
            faq_json_to_html,
            inject_section,
            update_product_body,
            get_product_body,
        )

        faq_html = faq_json_to_html(state.draft_content or "")
        if not faq_html:
            return
        current_body = (
            await get_product_body(
                state.shop_id, creds["access_token"], state.product_id
            )
        ) or ""
        new_body = inject_section(
            current_body,
            faq_html,
            "<!-- cba-faq-start -->",
            "<!-- cba-faq-end -->",
            position="append",
        )
        await update_product_body(
            shop_domain=state.shop_id,
            access_token=creds["access_token"],
            product_id=state.product_id,
            html=new_body,
        )

    async def publish_hero_overwrite(self, state: Any, creds: dict) -> None:
        """Convert Hero JSON → HTML and overwrite hero section in product description."""
        from src.ecommerce.services.shopify_service import (
            hero_json_to_html,
            inject_section,
            update_product_body,
            get_product_body,
        )

        hero_html = hero_json_to_html(state.draft_content or "")
        if not hero_html:
            return
        current_body = (
            await get_product_body(
                state.shop_id, creds["access_token"], state.product_id
            )
        ) or ""
        new_body = inject_section(
            current_body,
            hero_html,
            "<!-- cba-hero-start -->",
            "<!-- cba-hero-end -->",
            position="prepend",
        )
        await update_product_body(
            shop_domain=state.shop_id,
            access_token=creds["access_token"],
            product_id=state.product_id,
            html=new_body,
        )

    async def publish_article(self, state: Any, creds: dict) -> None:
        """Push blog-post draft_content → Shopify article."""
        from src.ecommerce.services.shopify_service import create_article, get_default_blog_id

        raw = state.raw_input or {}
        blog_id = raw.get("blog_id", "")
        if not blog_id:
            blog_id = await get_default_blog_id(
                shop_domain=state.shop_id,
                access_token=creds["access_token"],
            )
        if not blog_id:
            raise ValueError(
                "No blog found on this Shopify store – cannot create article"
            )

        title = raw.get("blog_title") or state.draft_title or "Untitled Post"
        body_html = state.draft_content or ""
        try:
            parsed = json.loads(body_html)
            if isinstance(parsed, dict):
                body_html = parsed.get("body_html", parsed.get("content", body_html))
                title = parsed.get("title", title)
        except (json.JSONDecodeError, TypeError):
            pass

        hero_url = raw.get("hero_url")

        await create_article(
            shop_domain=state.shop_id,
            access_token=creds["access_token"],
            blog_id=blog_id,
            title=title,
            body_html=body_html,
            image_url=hero_url,
        )

    async def publish_collection(self, state: Any, creds: dict) -> None:
        """Create a Shopify collection from draft_content."""
        from src.ecommerce.services.shopify_service import create_collection

        raw = state.raw_input or {}
        ctx = raw.get("context", {}) if isinstance(raw.get("context"), dict) else {}
        collection_name = (
            raw.get("collection_name")
            or ctx.get("collection_name")
            or raw.get("product_name")
            or "Untitled Collection"
        )

        desc_html = state.draft_content or ""
        try:
            parsed = json.loads(desc_html)
            if isinstance(parsed, dict):
                desc_html = parsed.get(
                    "description_html",
                    parsed.get("description", parsed.get("content", desc_html)),
                )
        except (json.JSONDecodeError, TypeError):
            pass

        product_ids = raw.get("product_ids") or []
        hero_url = raw.get("hero_url")

        await create_collection(
            shop_domain=state.shop_id,
            access_token=creds["access_token"],
            title=collection_name,
            description_html=desc_html,
            product_ids=product_ids,
            image_url=hero_url,
        )

    # ------------------------------------------------------------------
    # PriceScout publish helpers
    # ------------------------------------------------------------------

    async def update_variant_price(
        self,
        shop_domain: str,
        access_token: str,
        variant_id: str,
        price: str,
    ) -> None:
        """Update a Shopify variant price."""
        from src.ecommerce.services.shopify_service import update_variant_price

        await update_variant_price(
            shop_domain=shop_domain,
            access_token=access_token,
            variant_id=variant_id,
            price=price,
        )

    # ------------------------------------------------------------------
    # Visual publish helpers (Pro tier)
    # ------------------------------------------------------------------

    async def publish_visual_assets(self, state: Any, creds: dict) -> None:
        """
        Push generated visual assets to Shopify:
        1. Append the **refined product image** to the Shopify product's
           media gallery (does NOT replace existing images).
        2. Upload ad + hero to the Media Library (for download / manual use).
        """
        from src.ecommerce.services.shopify_service import (
            upload_media_to_shopify,
            add_product_image,
        )
        import httpx

        assets = getattr(state, "visual_assets", None) or {}
        access_token = creds.get("access_token", "")

        if not access_token:
            logger.warning("publish_visual_assets: no access_token, skipping")
            return

        product_name = (state.raw_input or {}).get("product_name", "product")
        product_id = getattr(state, "product_id", "")

        # ── 1. Append refined image to the Shopify product gallery ──
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
                logger.info(
                    "✅ Refined image appended to product %s: %s (%s)",
                    product_id, media_gid, state.shop_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to append refined image to product %s (%s): %s",
                    product_id, state.shop_id, str(e),
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

                file_gid = await upload_media_to_shopify(
                    shop_domain=state.shop_id,
                    access_token=access_token,
                    image_bytes=image_bytes,
                    filename=filename,
                    alt_text=f"{product_name} - {asset_type} visual",
                )
                logger.info(
                    "✅ Visual asset '%s' published to Shopify: %s (%s)",
                    asset_type, file_gid, state.shop_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to publish visual asset '%s' to Shopify (%s): %s",
                    asset_type, state.shop_id, str(e),
                )

    # ------------------------------------------------------------------
    # Marketing publish helpers
    # ------------------------------------------------------------------

    async def trigger_flow_event(
        self,
        shop_domain: str,
        access_token: str,
        event_topic: str,
        payload: dict,
    ) -> None:
        """Trigger a Shopify Flow event."""
        from src.ecommerce.services.shopify_service import trigger_flow_event

        await trigger_flow_event(
            shop_domain=shop_domain,
            access_token=access_token,
            event_topic=event_topic,
            payload=payload,
        )

"""
MetaService - Meta (Facebook/Instagram) Graph API interactions.

Handles autonomous publishing of ad creatives and social posts
to Meta pages via the Graph API. Pro tier only.
"""

import httpx
from typing import Optional, Tuple
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

META_GRAPH_API = "https://graph.facebook.com/v19.0"


class MetaService:
    """
    Client for the Meta Graph API.

    Usage:
        meta = MetaService()
        result = await meta.post_ad(
            page_id="123456",
            access_token="EAA...",
            caption="Check out our new product!",
            image_url="https://cdn.shopify.com/...",
        )
    """

    async def post_ad(
        self,
        page_id: str,
        access_token: str,
        caption: str,
        image_url: Optional[str] = None,
        link: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Post a photo/link ad to a Meta (Facebook) Page.

        If ``image_url`` is provided, creates a photo post.
        Otherwise creates a text/link post.

        Args:
            page_id: Facebook Page ID
            access_token: Page access token with ``pages_manage_posts`` permission
            caption: Post text / caption
            image_url: Optional image URL to attach
            link: Optional link URL

        Returns:
            Tuple of (success: bool, error_or_post_id: Optional[str])
        """
        try:
            if image_url:
                url = f"{META_GRAPH_API}/{page_id}/photos"
                payload = {
                    "url": image_url,
                    "caption": caption,
                    "access_token": access_token,
                }
            else:
                url = f"{META_GRAPH_API}/{page_id}/feed"
                payload = {
                    "message": caption,
                    "access_token": access_token,
                }
                if link:
                    payload["link"] = link

            async with httpx.AsyncClient() as client:
                resp = await client.post(url, data=payload)

                if resp.status_code in (200, 201):
                    data = resp.json()
                    post_id = data.get("id") or data.get("post_id")
                    logger.info(
                        "✅ Meta post published page=%s post_id=%s",
                        page_id,
                        post_id,
                    )
                    return True, post_id
                else:
                    error_data = resp.json()
                    error_msg = (
                        error_data.get("error", {}).get("message")
                        or resp.text
                    )
                    logger.error(
                        "❌ Meta post failed page=%s status=%d error=%s",
                        page_id,
                        resp.status_code,
                        error_msg,
                    )
                    return False, error_msg

        except Exception as e:
            logger.exception("Meta post_ad exception page=%s", page_id)
            return False, str(e)

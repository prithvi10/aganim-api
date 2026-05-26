"""
R2StorageService -- Cloudflare R2 (S3-compatible) storage for visual assets.

Stores generated visual assets with a 7-day TTL. Falls back to local disk
storage when R2 is not configured (development mode).

Required env vars (production):
    R2_ENDPOINT          -- e.g. https://<account_id>.r2.cloudflarestorage.com
    R2_ACCESS_KEY_ID     -- R2 access key
    R2_SECRET_ACCESS_KEY -- R2 secret key
    R2_BUCKET            -- Bucket name (e.g. "visual-assets")
    R2_PUBLIC_URL        -- Public URL prefix for the bucket (e.g. https://assets.example.com)
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)


def _get_boto3():
    """Lazily import boto3."""
    try:
        import boto3
        return boto3
    except ImportError:
        raise ImportError(
            "boto3 is required for R2 storage. "
            "Install it with: pip install boto3"
        )


class R2StorageService:
    """
    Upload visual assets to Cloudflare R2 with a 7-day TTL.

    Falls back to writing files to ``tmp/visual_assets/`` when the
    ``R2_ENDPOINT`` env var is not configured (local dev mode).

    Usage::

        r2 = R2StorageService()
        url = await r2.upload_asset(
            data=png_bytes,
            key="visual/shop.myshopify.com/abc123/refined.png",
            content_type="image/png",
        )
    """

    # 7-day TTL expressed as metadata (R2 lifecycle rules enforce actual deletion)
    TTL_DAYS = 7

    def __init__(
        self,
        endpoint: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        bucket: str | None = None,
        public_url: str | None = None,
    ):
        self._endpoint = endpoint or os.getenv("R2_ENDPOINT", "")
        self._access_key_id = access_key_id or os.getenv("R2_ACCESS_KEY_ID", "")
        self._secret_access_key = secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY", "")
        self._bucket = bucket or os.getenv("R2_BUCKET", "visual-assets")
        self._public_url = (public_url or os.getenv("R2_PUBLIC_URL", "")).rstrip("/")
        self._client = None

    @property
    def is_configured(self) -> bool:
        """Return True if R2 credentials are set."""
        return bool(self._endpoint and self._access_key_id and self._secret_access_key)

    def _get_client(self):
        """Get or create the S3-compatible boto3 client."""
        if self._client is None:
            boto3 = _get_boto3()
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
                region_name="auto",
            )
        return self._client

    async def upload_asset(
        self,
        data: bytes,
        key: str,
        content_type: str = "image/png",
    ) -> str:
        """
        Upload asset bytes and return a public URL.

        Args:
            data: Raw file bytes.
            key: Object key (e.g. ``visual/shop/mission_id/refined.png``).
            content_type: MIME type.

        Returns:
            Public URL for the uploaded asset.
        """
        if not self.is_configured:
            return await self._local_fallback(data, key, content_type)

        return await self._upload_to_r2(data, key, content_type)

    async def _upload_to_r2(
        self,
        data: bytes,
        key: str,
        content_type: str,
    ) -> str:
        """Upload to Cloudflare R2 via the S3-compatible API."""
        import asyncio
        import io

        client = self._get_client()

        def _put():
            client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=io.BytesIO(data),
                ContentType=content_type,
                Metadata={
                    "ttl-days": str(self.TTL_DAYS),
                },
            )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _put)

        # Build public URL
        if self._public_url:
            url = f"{self._public_url}/{key}"
        else:
            url = f"{self._endpoint}/{self._bucket}/{key}"

        logger.info(
            "[R2Storage] uploaded key=%s size=%d bytes url=%s",
            key, len(data), url,
        )
        return url

    async def _local_fallback(
        self,
        data: bytes,
        key: str,
        content_type: str,
    ) -> str:
        """
        Write to local disk when R2 is not configured (dev mode).

        Files are stored under ``tmp/visual_assets/<key>``.
        """
        base_dir = Path("tmp/visual_assets")
        file_path = base_dir / key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)

        local_path = str(file_path)
        logger.info(
            "[R2Storage] local_fallback key=%s size=%d bytes path=%s",
            key, len(data), local_path,
        )
        return local_path

    async def list_objects_by_prefix(
        self,
        prefix: str,
        bucket: str | None = None,
    ) -> list[str]:
        """
        List object filenames under a given prefix in the bucket.

        Args:
            prefix: Key prefix (e.g. ``"beta_outreach/musubi/"``).
            bucket: Override bucket name (defaults to the instance bucket).

        Returns:
            List of filenames (prefix stripped), e.g. ``["1_rewrite.png", "2_seo.png"]``.
            Returns empty list if R2 is not configured or prefix has no objects.
        """
        if not self.is_configured:
            return self._list_local_fallback(prefix)

        import asyncio

        client = self._get_client()
        target_bucket = bucket or self._bucket

        def _list():
            results: list[str] = []
            continuation_token = None
            while True:
                kwargs = {
                    "Bucket": target_bucket,
                    "Prefix": prefix,
                    "MaxKeys": 1000,
                }
                if continuation_token:
                    kwargs["ContinuationToken"] = continuation_token
                resp = client.list_objects_v2(**kwargs)
                for obj in resp.get("Contents", []):
                    key = obj["Key"]
                    filename = key[len(prefix):] if key.startswith(prefix) else key
                    if filename:
                        results.append(filename)
                if not resp.get("IsTruncated"):
                    break
                continuation_token = resp.get("NextContinuationToken")
            return results

        loop = asyncio.get_running_loop()
        filenames = await loop.run_in_executor(None, _list)

        logger.info(
            "[R2Storage] list prefix=%s bucket=%s found=%d files",
            prefix, target_bucket, len(filenames),
        )
        return filenames

    def _list_local_fallback(self, prefix: str) -> list[str]:
        """List files from local fallback directory matching a prefix."""
        base_dir = Path("tmp/visual_assets") / prefix
        if not base_dir.exists():
            return []
        return [f.name for f in base_dir.iterdir() if f.is_file()]

    @staticmethod
    def build_key(
        shop_domain: str,
        mission_id: str,
        asset_type: str,
        extension: str = "png",
    ) -> str:
        """
        Build a storage key for a visual asset.

        Args:
            shop_domain: e.g. ``"myshop.myshopify.com"``
            mission_id: Mission UUID hex.
            asset_type: One of ``"refined"``, ``"ad"``, ``"hero"``.
            extension: File extension (default ``"png"``).

        Returns:
            Key string like ``visual/myshop.myshopify.com/abc123/refined.png``.
        """
        return f"visual/{shop_domain}/{mission_id}/{asset_type}.{extension}"

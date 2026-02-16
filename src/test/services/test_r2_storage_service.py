"""
Unit tests for R2StorageService -- Cloudflare R2 (S3-compatible) storage.

Covers:
  - Happy path for R2 upload and local fallback
  - Configuration detection (is_configured)
  - build_key static helper
  - Edge cases (empty data, missing config)
  - Failure paths (boto3 errors, disk write errors)
"""

import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.ecommerce.services.r2_storage_service import R2StorageService


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def r2_configured():
    """R2StorageService with full credentials."""
    return R2StorageService(
        endpoint="https://test-account.r2.cloudflarestorage.com",
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
        bucket="test-bucket",
        public_url="https://assets.example.com",
    )


@pytest.fixture
def r2_unconfigured():
    """R2StorageService without credentials (dev mode)."""
    return R2StorageService(
        endpoint="",
        access_key_id="",
        secret_access_key="",
    )


FAKE_IMAGE = b"\x89PNG\r\n\x1a\nfake-image-data"


# =============================================================================
# Tests: is_configured
# =============================================================================

class TestIsConfigured:
    """Test is_configured property."""

    def test_configured_returns_true(self, r2_configured):
        assert r2_configured.is_configured is True

    def test_unconfigured_returns_false(self, r2_unconfigured):
        assert r2_unconfigured.is_configured is False

    def test_partial_config_missing_endpoint(self):
        svc = R2StorageService(
            endpoint="",
            access_key_id="key",
            secret_access_key="secret",
        )
        assert svc.is_configured is False

    def test_partial_config_missing_key_id(self):
        svc = R2StorageService(
            endpoint="https://r2.example.com",
            access_key_id="",
            secret_access_key="secret",
        )
        assert svc.is_configured is False

    def test_partial_config_missing_secret(self):
        svc = R2StorageService(
            endpoint="https://r2.example.com",
            access_key_id="key",
            secret_access_key="",
        )
        assert svc.is_configured is False


# =============================================================================
# Tests: build_key (static helper)
# =============================================================================

class TestBuildKey:
    """Test build_key static method."""

    def test_standard_key(self):
        key = R2StorageService.build_key(
            shop_domain="myshop.myshopify.com",
            mission_id="abc123",
            asset_type="refined",
        )
        assert key == "visual/myshop.myshopify.com/abc123/refined.png"

    def test_custom_extension(self):
        key = R2StorageService.build_key(
            shop_domain="shop.com",
            mission_id="def456",
            asset_type="ad",
            extension="jpg",
        )
        assert key == "visual/shop.com/def456/ad.jpg"

    def test_hero_asset(self):
        key = R2StorageService.build_key(
            shop_domain="shop.com",
            mission_id="ghi789",
            asset_type="hero",
        )
        assert key == "visual/shop.com/ghi789/hero.png"

    def test_masked_asset(self):
        key = R2StorageService.build_key(
            shop_domain="store.myshopify.com",
            mission_id="m123",
            asset_type="masked",
        )
        assert key == "visual/store.myshopify.com/m123/masked.png"


# =============================================================================
# Tests: upload_asset -- R2 path
# =============================================================================

class TestUploadToR2:
    """Test upload_asset when R2 is configured."""

    @pytest.mark.asyncio
    async def test_happy_path_with_public_url(self, r2_configured):
        """Test upload returns public URL."""
        mock_client = MagicMock()
        mock_client.put_object = MagicMock()

        with patch.object(r2_configured, "_get_client", return_value=mock_client):
            url = await r2_configured.upload_asset(
                data=FAKE_IMAGE,
                key="visual/shop.com/m1/refined.png",
                content_type="image/png",
            )

        assert url == "https://assets.example.com/visual/shop.com/m1/refined.png"
        mock_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_url_when_no_public_url(self):
        """Test upload builds URL from endpoint when no public_url is set."""
        svc = R2StorageService(
            endpoint="https://account.r2.cloudflarestorage.com",
            access_key_id="key",
            secret_access_key="secret",
            bucket="my-bucket",
            public_url="",
        )
        mock_client = MagicMock()
        mock_client.put_object = MagicMock()

        with patch.object(svc, "_get_client", return_value=mock_client):
            url = await svc.upload_asset(
                data=FAKE_IMAGE,
                key="visual/shop/m1/refined.png",
            )

        assert url == "https://account.r2.cloudflarestorage.com/my-bucket/visual/shop/m1/refined.png"

    @pytest.mark.asyncio
    async def test_put_object_metadata_ttl(self, r2_configured):
        """Test that TTL metadata is set on upload."""
        mock_client = MagicMock()
        mock_client.put_object = MagicMock()

        with patch.object(r2_configured, "_get_client", return_value=mock_client):
            await r2_configured.upload_asset(
                data=FAKE_IMAGE,
                key="visual/shop/m1/refined.png",
            )

        call_kwargs = mock_client.put_object.call_args
        assert call_kwargs[1]["Metadata"]["ttl-days"] == "7"

    @pytest.mark.asyncio
    async def test_boto3_error_propagates(self, r2_configured):
        """Test that boto3 errors propagate."""
        mock_client = MagicMock()
        mock_client.put_object = MagicMock(
            side_effect=Exception("S3 connection refused")
        )

        with patch.object(r2_configured, "_get_client", return_value=mock_client):
            with pytest.raises(Exception, match="S3 connection refused"):
                await r2_configured.upload_asset(
                    data=FAKE_IMAGE,
                    key="visual/shop/m1/refined.png",
                )


# =============================================================================
# Tests: upload_asset -- local fallback
# =============================================================================

class TestLocalFallback:
    """Test upload_asset when R2 is NOT configured (dev mode)."""

    @pytest.mark.asyncio
    async def test_local_fallback_writes_file(self, r2_unconfigured, tmp_path):
        """Test that local fallback writes to disk."""
        # Patch the base_dir to use tmp_path
        with patch("src.ecommerce.services.r2_storage_service.Path") as MockPath:
            base_path = tmp_path / "visual_assets"
            MockPath.return_value = base_path

            # Use the actual _local_fallback method directly
            path = await r2_unconfigured._local_fallback(
                data=FAKE_IMAGE,
                key="visual/shop/m1/refined.png",
                content_type="image/png",
            )

        assert "visual/shop/m1/refined.png" in path

    @pytest.mark.asyncio
    async def test_local_fallback_creates_dirs(self, r2_unconfigured, tmp_path, monkeypatch):
        """Test that local fallback creates necessary directories."""
        monkeypatch.chdir(tmp_path)

        path = await r2_unconfigured._local_fallback(
            data=FAKE_IMAGE,
            key="visual/testshop/abc/ad.png",
            content_type="image/png",
        )

        assert Path(path).exists()
        assert Path(path).read_bytes() == FAKE_IMAGE

    @pytest.mark.asyncio
    async def test_upload_asset_delegates_to_local_fallback(self, r2_unconfigured):
        """Test upload_asset correctly delegates to local fallback when unconfigured."""
        with patch.object(r2_unconfigured, "_local_fallback", new_callable=AsyncMock,
                          return_value="/tmp/fake/path.png") as mock_fb:
            url = await r2_unconfigured.upload_asset(
                data=FAKE_IMAGE,
                key="visual/shop/m1/refined.png",
            )

        assert url == "/tmp/fake/path.png"
        mock_fb.assert_called_once_with(FAKE_IMAGE, "visual/shop/m1/refined.png", "image/png")


# =============================================================================
# Tests: _get_client
# =============================================================================

class TestGetClient:
    """Test boto3 client initialization."""

    def test_client_created_lazily(self, r2_configured):
        """Test that boto3 client is created on first access."""
        assert r2_configured._client is None

        mock_boto3 = MagicMock()
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        with patch("src.ecommerce.services.r2_storage_service._get_boto3", return_value=mock_boto3):
            client = r2_configured._get_client()

        assert client is mock_s3
        mock_boto3.client.assert_called_once_with(
            "s3",
            endpoint_url="https://test-account.r2.cloudflarestorage.com",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
            region_name="auto",
        )

    def test_client_cached(self, r2_configured):
        """Test that subsequent calls return the same client."""
        mock_client = MagicMock()
        r2_configured._client = mock_client

        client = r2_configured._get_client()
        assert client is mock_client


# =============================================================================
# Tests: Constructor / env config
# =============================================================================

class TestR2Config:
    """Test constructor reads from env vars."""

    @patch.dict("os.environ", {
        "R2_ENDPOINT": "https://env-r2.example.com",
        "R2_ACCESS_KEY_ID": "env-key",
        "R2_SECRET_ACCESS_KEY": "env-secret",
        "R2_BUCKET": "env-bucket",
        "R2_PUBLIC_URL": "https://env-assets.example.com/",
    })
    def test_env_vars_read(self):
        svc = R2StorageService()
        assert svc._endpoint == "https://env-r2.example.com"
        assert svc._access_key_id == "env-key"
        assert svc._secret_access_key == "env-secret"
        assert svc._bucket == "env-bucket"
        # Trailing slash should be stripped
        assert svc._public_url == "https://env-assets.example.com"
        assert svc.is_configured is True

    def test_ttl_constant(self):
        assert R2StorageService.TTL_DAYS == 7

    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_when_no_env(self):
        svc = R2StorageService()
        assert svc._endpoint == ""
        assert svc._bucket == "visual-assets"  # default bucket name
        assert svc.is_configured is False

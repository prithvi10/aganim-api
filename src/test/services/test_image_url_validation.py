"""
Unit tests for validate_image_url -- SSRF prevention for the visual pipeline.

Covers:
  ✅ Happy paths  – all accepted Shopify CDN patterns
  ❌ Rejection    – non-HTTPS, wrong host, internal IPs, no extension, etc.
  🧪 Edge cases   – whitespace, query params, fal.media intermediate URLs
"""

import pytest

from src.ecommerce.services.visual_service import (
    validate_image_url,
    ImageURLValidationError,
)


# =============================================================================
# HAPPY PATHS — URLs that must be accepted
# =============================================================================

class TestValidateImageURL_HappyPaths:
    """URLs from Shopify CDN should pass validation."""

    def test_standard_shopify_cdn_png(self):
        url = "https://cdn.shopify.com/s/files/1/0123/4567/8901/products/blue-widget.png"
        assert validate_image_url(url) == url

    def test_standard_shopify_cdn_jpg(self):
        url = "https://cdn.shopify.com/s/files/1/0123/4567/8901/products/blue-widget.jpg"
        assert validate_image_url(url) == url

    def test_standard_shopify_cdn_jpeg(self):
        url = "https://cdn.shopify.com/s/files/1/0123/4567/8901/products/blue-widget.jpeg"
        assert validate_image_url(url) == url

    def test_standard_shopify_cdn_webp(self):
        url = "https://cdn.shopify.com/s/files/1/0123/4567/8901/products/blue-widget.webp"
        assert validate_image_url(url) == url

    def test_standard_shopify_cdn_gif(self):
        url = "https://cdn.shopify.com/s/files/1/0123/4567/8901/products/animated-demo.gif"
        assert validate_image_url(url) == url

    def test_standard_shopify_cdn_avif(self):
        url = "https://cdn.shopify.com/s/files/1/0123/4567/8901/products/next-gen.avif"
        assert validate_image_url(url) == url

    def test_shopify_cdn_with_query_params(self):
        """Shopify often appends ?v=timestamp or width params."""
        url = "https://cdn.shopify.com/s/files/1/0001/products/img.png?v=1714000000"
        assert validate_image_url(url) == url

    def test_shopifycdn_net(self):
        url = "https://cdn.shopifycdn.net/s/files/1/0001/products/product.jpg"
        assert validate_image_url(url) == url

    def test_per_store_myshopify_com_domain(self):
        """Some stores serve images from {store}.myshopify.com."""
        url = "https://my-cool-store.myshopify.com/cdn/shop/products/hero.png"
        assert validate_image_url(url) == url

    def test_whitespace_stripped(self):
        url = "  https://cdn.shopify.com/s/files/1/0001/products/img.png  "
        assert validate_image_url(url) == url.strip()


# =============================================================================
# REJECTION — URLs that MUST be blocked (SSRF vectors)
# =============================================================================

class TestValidateImageURL_Rejection:
    """Untrusted or malicious URLs must raise ImageURLValidationError."""

    # -- empty / None --
    def test_empty_string_raises(self):
        with pytest.raises(ImageURLValidationError, match="empty"):
            validate_image_url("")

    def test_none_raises(self):
        with pytest.raises(ImageURLValidationError, match="empty"):
            validate_image_url(None)

    def test_non_string_raises(self):
        with pytest.raises(ImageURLValidationError, match="empty"):
            validate_image_url(123)

    # -- wrong scheme --
    def test_http_url_rejected(self):
        with pytest.raises(ImageURLValidationError, match="HTTPS"):
            validate_image_url("http://cdn.shopify.com/s/files/1/img.png")

    def test_ftp_url_rejected(self):
        with pytest.raises(ImageURLValidationError, match="HTTPS"):
            validate_image_url("ftp://cdn.shopify.com/s/files/1/img.png")

    def test_file_url_rejected(self):
        with pytest.raises(ImageURLValidationError, match="HTTPS"):
            validate_image_url("file:///etc/passwd")

    def test_data_url_rejected(self):
        with pytest.raises(ImageURLValidationError, match="HTTPS"):
            validate_image_url("data:image/png;base64,iVBOR...")

    def test_javascript_url_rejected(self):
        with pytest.raises(ImageURLValidationError, match="HTTPS"):
            validate_image_url("javascript:alert(1)")

    # -- untrusted hosts --
    def test_aws_metadata_endpoint_rejected(self):
        """Classic SSRF vector: AWS instance metadata."""
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url("https://169.254.169.254/latest/meta-data/img.png")

    def test_internal_ip_rejected(self):
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url("https://10.0.0.1/internal/secret.png")

    def test_localhost_rejected(self):
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url("https://localhost/admin/img.png")

    def test_random_external_domain_rejected(self):
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url("https://evil.com/phishing/product.png")

    def test_look_alike_shopify_domain_rejected(self):
        """Subdomain confusion: cdn.shopify.com.evil.com."""
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url("https://cdn.shopify.com.evil.com/s/files/img.png")

    def test_shopify_api_domain_rejected(self):
        """Only CDN hosts are allowed, not the admin API."""
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url("https://my-store.myshopify.com.attacker.com/img.png")

    def test_google_storage_rejected_without_fal_flag(self):
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url(
                "https://storage.googleapis.com/fal-media/abc123/img.png"
            )

    def test_fal_media_rejected_by_default(self):
        """fal.media URLs are only allowed when allow_fal_media=True."""
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url("https://fal.media/files/abc/img.png")

    # -- bad extensions --
    def test_no_extension_rejected(self):
        with pytest.raises(ImageURLValidationError, match="extension"):
            validate_image_url("https://cdn.shopify.com/s/files/1/0001/products/noext")

    def test_html_extension_rejected(self):
        with pytest.raises(ImageURLValidationError, match="extension"):
            validate_image_url("https://cdn.shopify.com/s/files/1/page.html")

    def test_svg_extension_rejected(self):
        """SVGs can contain scripts — block them."""
        with pytest.raises(ImageURLValidationError, match="extension"):
            validate_image_url("https://cdn.shopify.com/s/files/1/logo.svg")

    def test_pdf_extension_rejected(self):
        with pytest.raises(ImageURLValidationError, match="extension"):
            validate_image_url("https://cdn.shopify.com/s/files/1/catalog.pdf")

    # -- no hostname --
    def test_no_hostname_rejected(self):
        with pytest.raises(ImageURLValidationError, match="no hostname"):
            validate_image_url("https:///path/to/img.png")


# =============================================================================
# EDGE CASES — fal.media intermediate URLs
# =============================================================================

class TestValidateImageURL_FalMediaFlag:
    """allow_fal_media=True enables intermediate pipeline URLs."""

    def test_fal_media_accepted_with_flag(self):
        url = "https://fal.media/files/abc123/output.png"
        assert validate_image_url(url, allow_fal_media=True) == url

    def test_fal_media_subdomain_accepted(self):
        url = "https://v3.fal.media/files/abc/result.jpg"
        assert validate_image_url(url, allow_fal_media=True) == url

    def test_google_storage_fal_bucket_accepted_with_flag(self):
        url = "https://storage.googleapis.com/fal-media/abc123/output.png"
        assert validate_image_url(url, allow_fal_media=True) == url

    def test_google_storage_non_fal_bucket_rejected_even_with_flag(self):
        """Only fal-* buckets on googleapis are allowed, not arbitrary ones."""
        with pytest.raises(ImageURLValidationError, match="not in the trusted allow-list"):
            validate_image_url(
                "https://storage.googleapis.com/my-bucket/img.png",
                allow_fal_media=True,
            )

    def test_shopify_cdn_still_accepted_with_fal_flag(self):
        url = "https://cdn.shopify.com/s/files/1/img.png"
        assert validate_image_url(url, allow_fal_media=True) == url


# =============================================================================
# EDGE CASES — miscellaneous
# =============================================================================

class TestValidateImageURL_EdgeCases:
    """Boundary conditions and unusual but valid inputs."""

    def test_uppercase_scheme_still_parses(self):
        """urlparse lowercases the scheme, so this should work."""
        url = "HTTPS://cdn.shopify.com/s/files/1/0001/products/img.png"
        # urlparse lowercases scheme
        assert validate_image_url(url) == url

    def test_uppercase_extension_accepted(self):
        url = "https://cdn.shopify.com/s/files/1/0001/products/IMG.PNG"
        assert validate_image_url(url) == url

    def test_mixed_case_hostname_accepted(self):
        """Hostnames are case-insensitive per RFC."""
        url = "https://CDN.Shopify.Com/s/files/1/0001/products/img.jpg"
        assert validate_image_url(url) == url

    def test_very_long_path_accepted(self):
        path = "/s/files/" + "/".join(["dir"] * 50) + "/img.png"
        url = f"https://cdn.shopify.com{path}"
        assert validate_image_url(url) == url

    def test_fragment_in_url_still_validates(self):
        url = "https://cdn.shopify.com/s/files/1/img.png#section"
        assert validate_image_url(url) == url

    def test_port_number_on_shopify_cdn_still_matches(self):
        """urlparse puts port in parsed.port, hostname remains cdn.shopify.com."""
        url = "https://cdn.shopify.com:443/s/files/1/img.png"
        assert validate_image_url(url) == url

    def test_myshopify_with_numeric_prefix_accepted(self):
        url = "https://123store.myshopify.com/cdn/shop/products/item.webp"
        assert validate_image_url(url) == url

    def test_myshopify_with_hyphens_accepted(self):
        url = "https://my-awesome-store-v2.myshopify.com/cdn/shop/products/item.jpeg"
        assert validate_image_url(url) == url


# =============================================================================
# ERROR CLASS TESTS
# =============================================================================

class TestImageURLValidationError:
    """Ensure the custom exception class behaves correctly."""

    def test_is_subclass_of_value_error(self):
        assert issubclass(ImageURLValidationError, ValueError)

    def test_message_preserved(self):
        try:
            raise ImageURLValidationError("test message")
        except ImageURLValidationError as e:
            assert str(e) == "test message"

    def test_catchable_as_value_error(self):
        with pytest.raises(ValueError):
            raise ImageURLValidationError("caught as ValueError")

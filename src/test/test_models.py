from src.main.models import RewriteRequest
from src.main.configs import DEFAULT_PRODUCT_CATEGORY
import pytest

def test_rewrite_request_defaults():
    """Test that default values are applied correctly."""
    request = RewriteRequest(
        product_name="Test Product",
        japanese_description="Test Description"
    )
    assert request.product_name == "Test Product"
    assert request.japanese_description == "Test Description"
    assert request.category == DEFAULT_PRODUCT_CATEGORY

def test_rewrite_request_custom_values():
    """Test that custom values are accepted."""
    request = RewriteRequest(
        product_name="Test Product",
        japanese_description="Test Description",
        category="Specific Category"
    )
    assert request.category == "Specific Category"

def test_rewrite_request_validation():
    """Test that required fields are validated."""
    with pytest.raises(ValueError):
        RewriteRequest(product_name="Missing Description")





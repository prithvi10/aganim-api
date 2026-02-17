from unittest.mock import MagicMock, patch

from src.agentic_core.rag.rag_service import get_brand_context


def test_get_brand_context_empty_inputs():
    db = MagicMock()
    assert get_brand_context(db, shop_id="", product_text="") == []
    assert get_brand_context(db, shop_id="shop.myshopify.com", product_text="") == []


def test_get_brand_context_returns_rows():
    """Test that get_brand_context delegates to _vector_search and returns results.

    We mock _vector_search directly because the cosine_distance SQLAlchemy
    operation requires pgvector which is not available in the test environment.
    """
    db = MagicMock()
    expected = [{"content": "Brand story chunk", "metadata": {"source_url": "https://example.com"}}]

    with patch("src.agentic_core.rag.rag_service._vector_search", return_value=expected):
        out = get_brand_context(db, shop_id="shop.myshopify.com", product_text="query text", limit=3)

    assert len(out) == 1
    assert out[0]["content"] == "Brand story chunk"

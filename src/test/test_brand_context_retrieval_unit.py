from unittest.mock import MagicMock, patch

from src.agentic_core.rag.rag_service import get_brand_context


def test_get_brand_context_empty_inputs():
    db = MagicMock()
    assert get_brand_context(db, shop_id="", product_text="") == []
    assert get_brand_context(db, shop_id="shop.myshopify.com", product_text="") == []


def test_get_brand_context_returns_rows():
    db = MagicMock()
    row = MagicMock()
    row.content = "Brand story chunk"
    row.metadata_json = {"source_url": "https://example.com"}

    query = db.query.return_value
    query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [row]

    with patch("src.agentic_core.rag.rag_service.embed_texts", return_value=[[0.1, 0.2]]):
        out = get_brand_context(db, shop_id="shop.myshopify.com", product_text="query text", limit=3)

    assert len(out) == 1
    assert out[0]["content"] == "Brand story chunk"

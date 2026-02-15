from unittest.mock import MagicMock, patch

from src.ecommerce.services.brand_ingest_service import ingest_brand_context


def test_ingest_brand_context_empty_returns_zero():
    db = MagicMock()
    db.bind = None
    result = ingest_brand_context(db, shop_id="shop.myshopify.com", raw_texts=[])
    assert result["inserted"] == 0
    assert result["chunk_count"] == 0


def test_ingest_brand_context_inserts_chunks_and_summary():
    db = MagicMock()
    db.bind = None
    mock_shop = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = mock_shop

    raw = [{"source_url": "https://example.com", "source_type": "web", "text": "Brand story. More story."}]

    # generate_json called once: clean_text with nested EN/JP
    clean_json = (
        '{"en": {"clean_text": "Brand story. More story.", "pillars": ["Heritage"]}, '
        '"ja": {"clean_text": "伝統の物語。", "pillars": ["伝統"]}}'
    )

    with patch(
        "src.ecommerce.services.brand_ingest_service._get_openai_service",
        return_value=MagicMock(generate_json=MagicMock(return_value=clean_json)),
    ):
        with patch(
            "src.ecommerce.services.brand_ingest_service.embed_texts",
            return_value=[[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]],
        ):
            result = ingest_brand_context(db, shop_id="shop.myshopify.com", raw_texts=raw, max_len=100)

    assert result["inserted"] == 2
    assert result["chunk_count"] == 2
    assert result["brand_context"] == {
        "en": {
            "clean_text": "Brand story. More story.",
            "pillars": ["Heritage"],
        },
        "ja": {
            "clean_text": "伝統の物語。",
            "pillars": ["伝統"],
        },
    }
    assert mock_shop.brand_context_status == "ready"
    assert mock_shop.brand_context == {
        "en": {
            "clean_text": "Brand story. More story.",
            "pillars": ["Heritage"],
        },
        "ja": {
            "clean_text": "伝統の物語。",
            "pillars": ["伝統"],
        },
    }
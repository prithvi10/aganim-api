from unittest.mock import MagicMock, patch

from src.main.service.brand_context_ingest import ingest_brand_context


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

    # generate_json called three times: clean + summary_en + summary_ja
    clean_json = '{"clean_text": "Brand story. More story.", "pillars": ["Heritage"]}'
    summary_en_json = '{"summary": "• Heritage craft", "key_facts": ["1885", "Kyoto"]}'
    summary_ja_json = '{"summary": "• 伝統の工芸", "key_facts": ["1885", "京都"]}'

    with patch(
        "src.main.service.brand_context_ingest.OpenAIService.generate_json",
        side_effect=[clean_json, summary_en_json, summary_ja_json],
    ):
        with patch("src.main.service.brand_context_ingest.embed_texts", return_value=[[0.1, 0.2, 0.3]]):
            result = ingest_brand_context(db, shop_id="shop.myshopify.com", raw_texts=raw, max_len=100)

    assert result["inserted"] == 1
    assert result["chunk_count"] == 1
    assert result["summary"] == "• Heritage craft"
    assert result["summary_en"] == "• Heritage craft"
    assert result["summary_ja"] == "• 伝統の工芸"
    assert result["key_facts"] == ["1885", "Kyoto"]
    assert mock_shop.brand_context_status == "ready"
    assert mock_shop.brand_context_summary_en == "• Heritage craft"
    assert mock_shop.brand_context_summary_ja == "• 伝統の工芸"
    assert mock_shop.brand_context_key_facts == '["1885", "Kyoto"]'
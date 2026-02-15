from src.ecommerce.core.generation import _render_brand_context_block, _should_use_brand_context


def test_brand_context_block_rendering():
    block = _render_brand_context_block(
        [
            {
                "content": "We are a Kyoto atelier focused on slow craft.",
                "metadata": {"source_url": "https://example.com/about"},
            }
        ]
    )
    # Header may evolve; assert we still emit the brand-context block and include provenance.
    assert "BRAND SOUL" in block or "BRAND_HERITAGE_CONTEXT" in block
    assert "https://example.com/about" in block
    assert "Kyoto atelier" in block


def test_brand_context_gating():
    assert _should_use_brand_context("Standard", True) is True
    assert _should_use_brand_context("Pro", True) is True
    assert _should_use_brand_context("Basic", True) is False
    assert _should_use_brand_context("Free", True) is False

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session

from src.ecommerce.core.generation import process_bulk_generation_request
from src.ecommerce.db.models import User, Plan
from src.ecommerce.api.models import BulkRewriteRequest


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.username = "test-shop.myshopify.com"
    return user


@pytest.fixture
def mock_plan():
    plan = MagicMock(spec=Plan)
    plan.name = "Pro"
    plan.can_stream_responses = True
    return plan


def _fake_openai_response():
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content='{"title":"T","description":"D","discovered_values": []}'))]
    resp.usage = MagicMock()
    resp.usage.total_tokens = 10
    return resp


@pytest.mark.asyncio
async def test_auto_convert_units_enabled_includes_prompt_block_for_english_locales(mock_db, mock_user, mock_plan):
    req = BulkRewriteRequest(
        product_name="P",
        japanese_description="サイズは10cm、重量は1kgです。",
        category="General",
        product_id=None,
        target_locales=["en", "fr"],
        auto_convert_units=True,
    )

    seen_prompts: list[str] = []

    def _capture_generate_copy(*, system_prompt: str, **kwargs):
        seen_prompts.append(system_prompt)
        return _fake_openai_response()

    with patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True), \
         patch("src.ecommerce.core.generation.openai_service.generate_copy", side_effect=_capture_generate_copy), \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value=None), \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as _mock_save:
        result = await process_bulk_generation_request(mock_db, req, mock_user, mock_plan)

    assert result["status"] == "success"
    assert len(seen_prompts) == 2

    en_prompt = next(p for p in seen_prompts if "TARGET LANGUAGE: en" in p)
    fr_prompt = next(p for p in seen_prompts if "TARGET LANGUAGE: fr" in p)

    assert "UNIT CONVERSION (STRICT, ENGLISH ONLY):" in en_prompt
    assert "UNIT CONVERSION (STRICT, ENGLISH ONLY):" not in fr_prompt


@pytest.mark.asyncio
async def test_auto_convert_units_disabled_does_not_include_prompt_block(mock_db, mock_user, mock_plan):
    req = BulkRewriteRequest(
        product_name="P",
        japanese_description="サイズは10cmです。",
        category="General",
        product_id=None,
        target_locales=["en"],
        auto_convert_units=False,
    )

    seen_prompts: list[str] = []

    def _capture_generate_copy(*, system_prompt: str, **kwargs):
        seen_prompts.append(system_prompt)
        return _fake_openai_response()

    with patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True), \
         patch("src.ecommerce.core.generation.openai_service.generate_copy", side_effect=_capture_generate_copy), \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value=None), \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as _mock_save:
        result = await process_bulk_generation_request(mock_db, req, mock_user, mock_plan)

    assert result["status"] == "success"
    assert len(seen_prompts) == 1
    assert "UNIT CONVERSION (STRICT, ENGLISH ONLY):" not in seen_prompts[0]


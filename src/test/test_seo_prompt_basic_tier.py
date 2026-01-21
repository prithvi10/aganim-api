import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session

from src.main.core.generation import process_bulk_generation_request
from src.main.db.db_models import User, Plan
from src.main.api.models import BulkRewriteRequest


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.username = "basic-shop.myshopify.com"
    return user


@pytest.fixture
def mock_plan_basic():
    plan = MagicMock(spec=Plan)
    plan.name = "Basic"
    plan.can_stream_responses = True
    return plan


def _fake_openai_response():
    resp = MagicMock()
    # Minimal valid response; missing seo_* will be normalized to "" and can self-heal later.
    resp.choices = [MagicMock(message=MagicMock(content='{"title":"T","description":"D","discovered_values": []}'))]
    resp.usage = MagicMock()
    resp.usage.total_tokens = 10
    return resp


@pytest.mark.asyncio
async def test_basic_tier_prompt_includes_seo_ctr_engineering_block(mock_db, mock_user, mock_plan_basic):
    req = BulkRewriteRequest(
        product_name="P",
        japanese_description="黒い革の財布。薄型。日本製。",
        category="General",
        product_id=None,
        target_locales=["en"],
        auto_convert_units=False,
    )

    seen_prompts: list[str] = []

    def _capture_generate_copy(*, system_prompt: str, **kwargs):
        seen_prompts.append(system_prompt)
        return _fake_openai_response()

    with patch("src.main.core.generation.limiter.is_allowed", return_value=True), \
         patch("src.main.core.generation.openai_service.generate_copy", side_effect=_capture_generate_copy), \
         patch("src.main.core.generation.get_shop_access_token", return_value=None), \
         patch("src.main.core.generation.save_product_content_with_locale", new_callable=AsyncMock):
        result = await process_bulk_generation_request(mock_db, req, mock_user, mock_plan_basic)

    assert result["status"] == "success"
    assert len(seen_prompts) == 1
    assert "### SEO & CTR ENGINEERING (BASIC TIER):" in seen_prompts[0]
    assert '"seo_alt_text": "..."' in seen_prompts[0] or "seo_alt_text" in seen_prompts[0]


@pytest.mark.asyncio
async def test_misc_toggle_in_prompt_moves_misc_section_when_off(mock_db, mock_user, mock_plan_basic):
    req = BulkRewriteRequest(
        product_name="P",
        japanese_description="黒い革の財布。薄型。日本製。メモ: SEOタイトル: xxx",
        category="General",
        product_id=None,
        target_locales=["en"],
        auto_convert_units=False,
        remove_irrelevant_content=False,
    )

    seen_prompts: list[str] = []

    def _capture_generate_copy(*, system_prompt: str, **kwargs):
        seen_prompts.append(system_prompt)
        return _fake_openai_response()

    with patch("src.main.core.generation.limiter.is_allowed", return_value=True), \
         patch("src.main.core.generation.openai_service.generate_copy", side_effect=_capture_generate_copy), \
         patch("src.main.core.generation.get_shop_access_token", return_value=None), \
         patch("src.main.core.generation.save_product_content_with_locale", new_callable=AsyncMock):
        await process_bulk_generation_request(mock_db, req, mock_user, mock_plan_basic)

    assert len(seen_prompts) == 1
    prompt = seen_prompts[0]
    assert "misc_information" in prompt
    assert "Move it into a dedicated field `misc_information`" in prompt


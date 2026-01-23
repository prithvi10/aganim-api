import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session

from src.main.core.generation import process_generation_request
from src.main.db.db_models import User, Plan
from src.main.api.models import RewriteRequest
from src.main.config.configs import OPENAI_MODEL


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.username = "test-shop.myshopify.com"
    return user


def _openai_resp_with_contract(*, description_html: str) -> MagicMock:
    """
    Build a fake OpenAI response object that matches the contract-safe schema so
    the SEO self-heal does not run (we want to isolate the pass-2 tables call).
    """
    payload = {
        "title": "New",
        "description": description_html,
        "seo_title": "SEO Title",
        "seo_description": "SEO Description",
        "seo_alt_text": "Alt text",
        "seo_insights": {},
        "misc_information": "",
        "discovered_values": [],
    }
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=str(payload).replace("'", '"')))]
    mock_resp.usage.total_tokens = 10
    return mock_resp


@pytest.mark.asyncio
async def test_standard_triggers_pass2_tables_and_saves_final_description(mock_db, mock_user):
    request = RewriteRequest(
        product_name="P",
        japanese_description="サイズ: 高さ10cm 幅5cm 重量100g",
        category="C",
        product_id=123,
        target_locale="en",
        auto_convert_units=True,
    )
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    mock_plan.name = "Standard"

    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    base_desc = "<div>Base</div>"
    final_desc = (
        "<div>Base</div>"
        "<h3>Product Specifications</h3><table><tbody><tr><td>Material</td><td>Cotton</td></tr></tbody></table>"
        "<h3>Detailed Dimensions</h3><table><tbody><tr><td>Height</td><td>10 cm</td><td>3.9 in</td></tr></tbody></table>"
    )

    pass2_json = (
        '{'
        f'"final_description_html": {final_desc!r},'
        '"product_specifications_table_html": "<h3>Product Specifications</h3><table></table>",'
        '"detailed_dimensions_table_html": "<h3>Detailed Dimensions</h3><table></table>",'
        '"removed_tables_count": 0'
        "}"
    ).replace("'", '"')

    with patch("src.main.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.main.core.generation.openai_service.generate_json", return_value=pass2_json) as mock_pass2, \
         patch("src.main.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.main.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.main.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=[]), \
         patch("src.main.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.core.generation.limiter.is_allowed", return_value=True):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        resp = await process_generation_request(db=mock_db, request=request, user=mock_user, plan=mock_plan)
        assert resp["status"] == "success"

        # Pass-2 should be invoked exactly once for Standard/Pro, using the cheapest model.
        assert mock_pass2.call_count == 1
        _, kwargs = mock_pass2.call_args
        assert kwargs.get("model") == OPENAI_MODEL
        assert kwargs.get("temperature") == 0.0
        assert kwargs.get("max_tokens") == 1100

        # Saved description should contain BOTH tables.
        mock_save_content.assert_called_once()
        saved_kwargs = mock_save_content.call_args.kwargs
        saved_desc = saved_kwargs["description"]
        assert "<h3>Product Specifications</h3>" in saved_desc
        assert "<h3>Detailed Dimensions</h3>" in saved_desc


@pytest.mark.asyncio
async def test_basic_does_not_trigger_pass2_tables(mock_db, mock_user):
    request = RewriteRequest(
        product_name="P",
        japanese_description="サイズ: 高さ10cm 幅5cm 重量100g",
        category="C",
        product_id=123,
        target_locale="en",
    )
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    mock_plan.name = "Basic"

    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    base_desc = "<div>Base</div>"

    with patch("src.main.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.main.core.generation.openai_service.generate_json") as mock_pass2, \
         patch("src.main.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.main.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.main.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.core.generation.limiter.is_allowed", return_value=True):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        resp = await process_generation_request(db=mock_db, request=request, user=mock_user, plan=mock_plan)
        assert resp["status"] == "success"

        # Basic must NOT run the pass-2 tables call.
        assert mock_pass2.call_count == 0

        mock_save_content.assert_called_once()
        saved_desc = mock_save_content.call_args.kwargs["description"]
        assert saved_desc == base_desc


@pytest.mark.asyncio
async def test_standard_pass2_invalid_json_falls_back_to_original_description(mock_db, mock_user):
    request = RewriteRequest(
        product_name="P",
        japanese_description="サイズ: 高さ10cm 幅5cm 重量100g",
        category="C",
        product_id=123,
        target_locale="en",
    )
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    mock_plan.name = "Standard"

    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    base_desc = "<div>Base</div>"

    with patch("src.main.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.main.core.generation.openai_service.generate_json", return_value="NOT JSON") as mock_pass2, \
         patch("src.main.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.main.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.main.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=[]), \
         patch("src.main.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.core.generation.limiter.is_allowed", return_value=True):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        resp = await process_generation_request(db=mock_db, request=request, user=mock_user, plan=mock_plan)
        assert resp["status"] == "success"
        assert mock_pass2.call_count == 1

        mock_save_content.assert_called_once()
        saved_desc = mock_save_content.call_args.kwargs["description"]
        assert saved_desc == base_desc


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


def _json_response_obj(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    resp.usage.total_tokens = 9
    return resp


@pytest.mark.asyncio
async def test_basic_includes_seo_recommendations_and_uses_cheapest_model(mock_db, mock_user):
    request = RewriteRequest(
        product_name="P",
        japanese_description="素材: 綿100% サイズ: 高さ10cm",
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

    recs_json = (
        '{'
        '"competitive_edge":{"headline":"Edge","copy":"Edge copy"},'
        '"buyer_intent":{"strategy":["Use buyer-intent phrasing","Answer common buyer questions"]}'
        '}'
    )

    with patch("src.main.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.main.core.generation.openai_service.generate_json_response", return_value=_json_response_obj(recs_json)) as mock_recs, \
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
        assert "seo_recommendations" in resp["data"]
        assert resp["data"]["seo_recommendations"]["competitive_edge"]["headline"] == "Edge"
        assert len(resp["data"]["seo_recommendations"]["buyer_intent"]["strategy"]) >= 1

        # Ensure cheapest model was requested.
        _, kwargs = mock_recs.call_args
        assert kwargs.get("model") == OPENAI_MODEL
        assert kwargs.get("temperature") == 0.0

        mock_save_content.assert_called_once()


@pytest.mark.asyncio
async def test_seo_recommendations_failure_is_non_blocking(mock_db, mock_user):
    request = RewriteRequest(
        product_name="P",
        japanese_description="素材: 綿100% サイズ: 高さ10cm",
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
         patch("src.main.core.generation.openai_service.generate_json_response", side_effect=Exception("timeout")), \
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
        # Should not crash; seo_recommendations may be absent.
        assert "seo_recommendations" not in resp["data"] or resp["data"]["seo_recommendations"] is None
        mock_save_content.assert_called_once()


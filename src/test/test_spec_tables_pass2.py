import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session

from src.ecommerce.core.generation import process_generation_request
from src.ecommerce.db.models import User, Plan
from src.ecommerce.api.models import RewriteRequest
from src.ecommerce.config.configs import OPENAI_MODEL


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
        '"seo_title": "SEO Title",'
        '"seo_description": "SEO Description",'
        '"product_specifications_table_html": "<h3>Product Specifications</h3><table></table>",'
        '"detailed_dimensions_table_html": "<h3>Detailed Dimensions</h3><table></table>",'
        '"removed_tables_count": 0'
        "}"
    ).replace("'", '"')

    with patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.ecommerce.core.generation.openai_service.generate_json", return_value=pass2_json) as mock_pass2, \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=[]), \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True):

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
        assert kwargs.get("temperature") == 0.1
        assert kwargs.get("max_tokens") == 1500

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

    with patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.ecommerce.core.generation.openai_service.generate_json") as mock_pass2, \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True):

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

    with patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.ecommerce.core.generation.openai_service.generate_json", return_value="NOT JSON") as mock_pass2, \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=[]), \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True):

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


@pytest.mark.asyncio
async def test_standard_pass2_uses_split_table_fields_when_final_html_missing_tables(mock_db, mock_user):
    """
    Regression: Sometimes the model returns a small/empty final_description_html but still provides the split
    table fields. We must still append the two tables deterministically.
    """
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

    pass2_json = (
        "{"
        '"final_description_html": "<div>Too short</div>",'
        '"seo_title": "T",'
        '"seo_description": "D",'
        '"product_specifications_table_html": "<table><tbody><tr><td>Weight</td><td>100 g</td><td>3.5 oz</td></tr></tbody></table>",'
        '"detailed_dimensions_table_html": "<table><tbody><tr><td>Height</td><td>10 cm</td><td>3.9 in</td></tr></tbody></table>",'
        '"removed_tables_count": 0'
        "}"
    )

    with patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.ecommerce.core.generation.openai_service.generate_json", return_value=pass2_json) as mock_pass2, \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=[]), \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        resp = await process_generation_request(db=mock_db, request=request, user=mock_user, plan=mock_plan)
        assert resp["status"] == "success"
        assert mock_pass2.call_count == 1

        mock_save_content.assert_called_once()
        saved_desc = mock_save_content.call_args.kwargs["description"]
        assert "<h3>Product Specifications</h3>" in saved_desc
        assert "<h3>Detailed Dimensions</h3>" in saved_desc
        assert "<table" in saved_desc.lower()


@pytest.mark.asyncio
async def test_standard_with_brand_soul_injects_context_in_pass2(mock_db, mock_user):
    request = RewriteRequest(
        product_name="P",
        japanese_description="Desc",
        category="C",
        product_id=123,
        target_locale="en",
        brand_soul_enabled=True,
    )
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    mock_plan.name = "Standard"

    mock_shop_info_resp = MagicMock()
    mock_shop_info_resp.status_code = 200
    mock_shop_info_resp.json.return_value = {"shop": {"primary_locale": "en"}}

    base_desc = "<div>Base</div>"
    pass2_json = (
        '{'
        '"final_description_html": "<div>With Soul</div>",'
        '"seo_title": "SEO",'
        '"seo_description": "SEO",'
        '"product_specifications_table_html": "<h3>Product Specifications</h3><table></table>",'
        '"detailed_dimensions_table_html": "<h3>Detailed Dimensions</h3><table></table>",'
        '"removed_tables_count": 0'
        '}'
    )

    with patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.ecommerce.core.generation.openai_service.generate_json", return_value=pass2_json) as mock_pass2, \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=[]), \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock), \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True), \
         patch("src.ecommerce.core.generation._build_brand_context_block", return_value="Verified Heritage"):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        await process_generation_request(db=mock_db, request=request, user=mock_user, plan=mock_plan)

        # Verify Pass 2 received brand context
        assert mock_pass2.call_count == 1
        _, kwargs = mock_pass2.call_args
        user_json = kwargs["user_json"]
        assert user_json["brand_context"] == "Verified Heritage"


@pytest.mark.asyncio
async def test_standard_pass2_updates_seo_fields_if_provided(mock_db, mock_user):
    request = RewriteRequest(
        product_name="P",
        japanese_description="Desc",
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
    pass2_json = (
        '{'
        '"final_description_html": "<div>Desc</div>",'
        '"seo_title": "Better Title",'
        '"seo_description": "Better Desc",'
        '"product_specifications_table_html": "<h3>Product Specifications</h3><table></table>",'
        '"detailed_dimensions_table_html": "<h3>Detailed Dimensions</h3><table></table>",'
        '"removed_tables_count": 0'
        '}'
    )

    with patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.ecommerce.core.generation.openai_service.generate_json", return_value=pass2_json), \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=[]), \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock), \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        resp = await process_generation_request(db=mock_db, request=request, user=mock_user, plan=mock_plan)

        # Verify response contains UPDATED seo fields
        assert resp["data"]["seo_title"] == "Better Title"
        assert resp["data"]["seo_description"] == "Better Desc"


@pytest.mark.asyncio
async def test_standard_pass2_malformed_tables_returns_fallback(mock_db, mock_user):
    request = RewriteRequest(
        product_name="P",
        japanese_description="Desc",
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
    # Malformed tables (no table tag)
    pass2_json = (
        '{'
        '"final_description_html": "<div>With Soul</div>",'
        '"seo_title": "Better Title",'
        '"seo_description": "Better Desc",'
        '"product_specifications_table_html": "Not a table",'
        '"detailed_dimensions_table_html": "Not a table",'
        '"removed_tables_count": 0'
        '}'
    )

    with patch("src.ecommerce.core.generation.openai_service.generate_copy", return_value=_openai_resp_with_contract(description_html=base_desc)), \
         patch("src.ecommerce.core.generation.openai_service.generate_json", return_value=pass2_json), \
         patch("src.ecommerce.core.generation.get_shop_access_token", return_value="token"), \
         patch("src.ecommerce.core.generation.httpx.AsyncClient") as MockClient, \
         patch("src.ecommerce.core.generation.serp_service.fetch_top_results", new_callable=AsyncMock, return_value=[]), \
         patch("src.ecommerce.core.generation.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True):

        mock_client = MockClient.return_value
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_shop_info_resp)

        resp = await process_generation_request(db=mock_db, request=request, user=mock_user, plan=mock_plan)

        # Fallback means:
        # 1. Description is original base_desc (no soul, no tables)
        # 2. SEO fields are original (from Pass 1, which are "SEO Title"/"SEO Description" in mock)
        
        mock_save_content.assert_called_once()
        saved_desc = mock_save_content.call_args.kwargs["description"]
        assert saved_desc == base_desc
        assert "With Soul" not in saved_desc
        
        assert resp["data"]["seo_title"] == "SEO Title"  # NOT "Better Title"

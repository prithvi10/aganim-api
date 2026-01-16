import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session

from src.main.core.generation import process_generation_request
from src.main.api.models import RewriteRequest
from src.main.db.db_models import User, Plan


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


@pytest.fixture
def mock_user():
    u = MagicMock(spec=User)
    u.username = "test-shop.myshopify.com"
    return u


def _fake_openai_response():
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content='{"title":"T","description":"D","discovered_values": []}'))]
    resp.usage = MagicMock()
    resp.usage.total_tokens = 10
    return resp


@pytest.mark.asyncio
async def test_basic_plan_forces_professional_tone(mock_db, mock_user):
    plan = MagicMock(spec=Plan)
    plan.name = "Basic"
    plan.can_stream_responses = False

    req = RewriteRequest(
        product_name="P",
        japanese_description="D",
        product_id=None,
        target_locale="en",
        tone_profile="luxury",  # should be ignored
    )

    seen: list[str] = []

    def _capture_generate_copy(*, system_prompt: str, **kwargs):
        seen.append(system_prompt)
        return _fake_openai_response()

    with patch("src.main.core.generation.limiter.is_allowed", return_value=True), \
         patch("src.main.core.generation.openai_service.generate_copy", side_effect=_capture_generate_copy):
        out = await process_generation_request(mock_db, req, mock_user, plan)

    assert out["status"] == "success"
    assert len(seen) == 1
    assert "TONE PROFILE: Professional/Standard" in seen[0]
    assert "TONE PROFILE: Luxury/Heritage" not in seen[0]


@pytest.mark.asyncio
async def test_standard_plan_injects_selected_tone(mock_db, mock_user):
    plan = MagicMock(spec=Plan)
    plan.name = "Standard"
    plan.can_stream_responses = False

    req = RewriteRequest(
        product_name="P",
        japanese_description="D",
        product_id=None,
        target_locale="en",
        tone_profile="luxury",
    )

    seen: list[str] = []

    def _capture_generate_copy(*, system_prompt: str, **kwargs):
        seen.append(system_prompt)
        return _fake_openai_response()

    with patch("src.main.core.generation.limiter.is_allowed", return_value=True), \
         patch("src.main.core.generation.openai_service.generate_copy", side_effect=_capture_generate_copy):
        out = await process_generation_request(mock_db, req, mock_user, plan)

    assert out["status"] == "success"
    assert len(seen) == 1
    assert "TONE PROFILE: Luxury/Heritage" in seen[0]
    assert "Shokunin" in seen[0] or "shokunin" in seen[0].lower()


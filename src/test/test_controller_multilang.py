import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session
from datetime import date

from src.main.api.main import app
from src.main.db.database import get_db
from src.main.db.db_models import User, Plan

client = TestClient(app)

# --- Mocks ---
def mock_get_db():
    return MagicMock(spec=Session)

app.dependency_overrides[get_db] = mock_get_db

@pytest.fixture
def mock_auth_context():
    mock_user = MagicMock(spec=User)
    mock_user.username = "test-shop.myshopify.com"
    mock_user.id = 1 
    mock_plan = MagicMock(spec=Plan)
    mock_plan.can_stream_responses = False
    return {
        "user": mock_user, "plan": mock_plan, "user_id": 1,
        "billing_cycle_start": date(2023, 1, 1), "current_usage": 0
    }

@pytest.mark.asyncio
async def test_get_shop_locales_success(mock_auth_context):
    """Test fetching shop locales via proxy endpoint."""
    shop = "test-shop.myshopify.com"
    
    mock_locales = [
        {"locale": "en", "primary": True},
        {"locale": "fr", "primary": False}
    ]
    
    with patch("src.main.api.controller.fetch_shop_locales", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"status": "success", "locales": mock_locales}

        response = client.get(f"/api/proxy/shop/locales?shop={shop}")

        assert response.status_code == 200
        assert len(response.json()["locales"]) == 2
        assert response.json()["locales"][0]["locale"] == "en"
        mock_fetch.assert_called_once()

@pytest.mark.asyncio
async def test_controller_delegates_to_core_generation(mock_auth_context):
    """Test that controller delegates generation request to core layer."""
    shop = "test-shop.myshopify.com"
    
    with patch("src.main.api.controller.validate_shop_and_quota", return_value=mock_auth_context), \
         patch("src.main.api.controller.process_generation_request", new_callable=AsyncMock) as mock_process:
        
        mock_process.return_value = {"status": "success", "data": {"title": "T", "description": "D"}}

        response = client.post(
            f"/api/proxy/generate-copy?shop={shop}",
            json={
                "product_name": "P", "japanese_description": "D", 
                "product_id": 123, "target_locale": "en"
            }
        )

        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_process.assert_called_once()

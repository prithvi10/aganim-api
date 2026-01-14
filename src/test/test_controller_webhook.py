import pytest
import json
import hashlib
import hmac
import base64
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session

from src.main.api.main import app
from src.main.db.database import get_db
from src.main.db.db_models import Plan
from src.main.api.models import OnboardingResponse

client = TestClient(app)

# Mock DB Session
def mock_get_db():
    return MagicMock(spec=Session)

app.dependency_overrides[get_db] = mock_get_db

# Mock Secret for HMAC
MOCK_SHOPIFY_SECRET = "test_secret_key"

@pytest.fixture
def webhook_payload():
    return {
        "myshopify_domain": "test-store.myshopify.com",
        "billing_plan": "Basic",
        "email": "merchant@example.com"
    }

@pytest.fixture
def mock_plan():
    plan = MagicMock(spec=Plan)
    plan.id = 1
    plan.name = "Basic"
    return plan

def generate_hmac(secret, body):
    digest = hmac.new(
        secret.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode('utf-8')

@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_webhook_subscription_success(webhook_payload, mock_plan):
    """Test successful webhook processing."""
    
    # Prepare request
    json_body = json.dumps(webhook_payload).encode('utf-8')
    hmac_sig = generate_hmac(MOCK_SHOPIFY_SECRET, json_body)
    headers = {"X-Shopify-Hmac-Sha256": hmac_sig}

    # Mock dependencies
    with patch("src.main.api.controller.get_plan_by_name", return_value=mock_plan) as mock_get_plan, \
         patch("src.main.api.controller.onboard_user") as mock_onboard:
        
        response = client.post(
            "/webhooks/subscription-activated",
            content=json_body, # Use content to preserve exact bytes for HMAC check in app
            headers=headers
        )

        assert response.status_code == 200
        mock_get_plan.assert_called_once()
        mock_onboard.assert_called_once()
        
        # Verify onboard_user was called with correct data
        args, _ = mock_onboard.call_args
        request_obj = args[1] # 0 is db, 1 is request
        assert request_obj.username == "test-store.myshopify.com"
        assert request_obj.plan_id == 1

def test_webhook_missing_header(webhook_payload):
    """Test webhook fails without HMAC header."""
    response = client.post(
        "/webhooks/subscription-activated",
        json=webhook_payload
    )
    assert response.status_code == 401
    assert "Unauthorized" in response.json()["detail"]

@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_webhook_invalid_signature(webhook_payload):
    """Test webhook fails with incorrect signature."""
    json_body = json.dumps(webhook_payload).encode('utf-8')
    headers = {"X-Shopify-Hmac-Sha256": "invalid_signature"}

    response = client.post(
        "/webhooks/subscription-activated",
        content=json_body,
        headers=headers
    )
    assert response.status_code == 401

@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_webhook_payload_missing_fields(webhook_payload):
    """Test webhook returns 200 (graceful fail) when payload is incomplete."""
    incomplete_payload = {"some_other_field": "value"}
    json_body = json.dumps(incomplete_payload).encode('utf-8')
    hmac_sig = generate_hmac(MOCK_SHOPIFY_SECRET, json_body)
    headers = {"X-Shopify-Hmac-Sha256": hmac_sig}

    response = client.post(
        "/webhooks/subscription-activated",
        content=json_body,
        headers=headers
    )
    
    # Should return 200 to acknowledge receipt even if processing failed
    assert response.status_code == 200

@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_webhook_plan_not_found(webhook_payload):
    """Test webhook returns 200 when plan is unknown."""
    json_body = json.dumps(webhook_payload).encode('utf-8')
    hmac_sig = generate_hmac(MOCK_SHOPIFY_SECRET, json_body)
    headers = {"X-Shopify-Hmac-Sha256": hmac_sig}

    with patch("src.main.api.controller.get_plan_by_name", return_value=None) as mock_get_plan, \
         patch("src.main.api.controller.onboard_user") as mock_onboard:

        response = client.post(
            "/webhooks/subscription-activated",
            content=json_body,
            headers=headers
        )

        assert response.status_code == 200
        mock_get_plan.assert_called_once()
        mock_onboard.assert_not_called()

@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_webhook_user_already_exists(webhook_payload, mock_plan):
    """Test webhook returns 200 when user exists (idempotency)."""
    json_body = json.dumps(webhook_payload).encode('utf-8')
    hmac_sig = generate_hmac(MOCK_SHOPIFY_SECRET, json_body)
    headers = {"X-Shopify-Hmac-Sha256": hmac_sig}

    # Simulate 409 Conflict from service
    from fastapi import HTTPException
    
    with patch("src.main.api.controller.get_plan_by_name", return_value=mock_plan), \
         patch("src.main.api.controller.onboard_user", side_effect=HTTPException(status_code=409, detail="Exists")):

        response = client.post(
            "/webhooks/subscription-activated",
            content=json_body,
            headers=headers
        )

        assert response.status_code == 200

@patch("src.main.security.security.SHOPIFY_API_SECRET", MOCK_SHOPIFY_SECRET)
def test_webhook_unexpected_error(webhook_payload, mock_plan):
    """Test webhook returns 200 on unexpected errors."""
    json_body = json.dumps(webhook_payload).encode('utf-8')
    hmac_sig = generate_hmac(MOCK_SHOPIFY_SECRET, json_body)
    headers = {"X-Shopify-Hmac-Sha256": hmac_sig}

    with patch("src.main.api.controller.get_plan_by_name", return_value=mock_plan), \
         patch("src.main.api.controller.onboard_user", side_effect=Exception("Unexpected Crash")):

        response = client.post(
            "/webhooks/subscription-activated",
            content=json_body,
            headers=headers
        )

        assert response.status_code == 200


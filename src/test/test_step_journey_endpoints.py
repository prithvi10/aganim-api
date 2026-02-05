"""
Integration tests for step-by-step journey API endpoints.

Tests the new endpoints:
- GET /api/missions/{mission_id}/status
- POST /api/missions/{mission_id}/run-step
- POST /api/missions/{mission_id}/continue
- POST /api/missions/{mission_id}/regenerate
- POST /api/missions/{mission_id}/skip
"""

import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from src.main.api.main import app


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def client():
    """Create test client with auth dependency override."""
    from src.main.api.shopify.shared import resolve_shop_domain
    
    # Override auth to return test shop
    app.dependency_overrides[resolve_shop_domain] = lambda: "test-shop.myshopify.com"
    
    with TestClient(app) as c:
        yield c
    
    # Clean up overrides
    app.dependency_overrides.clear()


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    return session


@pytest.fixture
def sample_mission():
    """Create a sample mission record."""
    from src.main.db.db_models import Mission
    
    mission = MagicMock(spec=Mission)
    mission.id = "test-mission-123"
    mission.shop_id = "test-shop.myshopify.com"
    mission.product_id = "prod-123"
    mission.status = "PENDING"
    mission.plan_tier = "Standard"
    mission.logs = []
    mission.error_message = None
    mission.created_at = datetime.now(timezone.utc)
    mission.completed_at = None
    mission.current_state = {
        "product_id": "prod-123",
        "shop_id": "test-shop.myshopify.com",
        "plan_tier": "Standard",
        "raw_input": {"title": "Test Product"},
        "status": "PENDING",
        "current_agent_index": 0,
        "skipped_agents": [],
        "agent_outputs": {},
        "workflow_agents": ["RewriterAgent", "MarketingAgent", "PriceScoutAgent", "ComplianceAgent"],
        "logs": [],
    }
    return mission


# =============================================================================
# Tests: GET /api/missions/{mission_id}/status
# =============================================================================

def test_get_mission_status_returns_structured_response(client, sample_mission):
    """Test that /status returns structured MissionStatusResponse."""
    from src.main.db.database import get_db
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.get(f"/api/missions/{sample_mission.id}/status")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["mission_id"] == sample_mission.id
    assert data["shop_id"] == sample_mission.shop_id
    assert data["status"] == "PENDING"
    assert data["current_agent_index"] == 0
    assert data["total_agents"] == 4
    assert "RewriterAgent" in data["workflow_agents"]
    
    app.dependency_overrides.clear()


def test_get_mission_status_not_found(client):
    """Test /status returns 404 for non-existent mission."""
    from src.main.db.database import get_db
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.get("/api/missions/nonexistent-id/status")
    
    assert response.status_code == 404
    
    app.dependency_overrides.clear()


def test_get_mission_status_includes_agent_outputs(client, sample_mission):
    """Test /status includes agent_outputs for completed steps."""
    from src.main.db.database import get_db
    
    sample_mission.current_state["agent_outputs"] = {
        "RewriterAgent": {"draft_title": "Test Title"}
    }
    sample_mission.current_state["current_agent_index"] = 1
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.get(f"/api/missions/{sample_mission.id}/status")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["current_agent_index"] == 1
    assert "RewriterAgent" in data["agent_outputs"]
    assert data["agent_outputs"]["RewriterAgent"]["draft_title"] == "Test Title"
    
    app.dependency_overrides.clear()


def test_get_mission_status_includes_skipped_agents(client, sample_mission):
    """Test /status includes skipped_agents list."""
    from src.main.db.database import get_db
    
    sample_mission.current_state["skipped_agents"] = ["MarketingAgent"]
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.get(f"/api/missions/{sample_mission.id}/status")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "MarketingAgent" in data["skipped_agents"]
    
    app.dependency_overrides.clear()


# =============================================================================
# Tests: POST /api/missions/{mission_id}/continue
# =============================================================================

def test_continue_step_advances_index(client, sample_mission):
    """Test /continue advances current_agent_index."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "success"
    assert data["current_agent_index"] == 1
    assert data["next_agent"] == "MarketingAgent"
    assert data["is_complete"] is False
    
    app.dependency_overrides.clear()


def test_continue_step_completes_at_end(client, sample_mission):
    """Test /continue marks complete at last agent."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 3  # Last agent
    # Add draft content for Shopify save
    sample_mission.current_state["draft_title"] = "Test Title"
    sample_mission.current_state["draft_content"] = "<p>Test content</p>"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    # Mock Shopify save functions - patch where they're used (imported inside the function)
    with patch("src.main.db.db_transactions.get_shop_access_token", return_value="test-token"), \
         patch("src.main.services.shopify_service.save_product_content_with_locale", new_callable=AsyncMock) as mock_save, \
         patch("src.main.services.shopify_service.save_product_metafields", new_callable=AsyncMock) as mock_metafields:
        
        response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["is_complete"] is True
    assert data["mission_status"] == "COMPLETED"
    
    app.dependency_overrides.clear()


def test_continue_step_rejects_wrong_status(client, sample_mission):
    """Test /continue rejects if mission not in AWAITING_APPROVAL."""
    from src.main.db.database import get_db
    
    sample_mission.status = "IN_PROGRESS"  # Wrong status
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    assert response.status_code == 400
    
    app.dependency_overrides.clear()


def test_continue_step_not_found(client):
    """Test /continue returns 404 for non-existent mission."""
    from src.main.db.database import get_db
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post("/api/missions/nonexistent-id/continue")
    
    assert response.status_code == 404
    
    app.dependency_overrides.clear()


# =============================================================================
# Tests: POST /api/missions/{mission_id}/regenerate
# =============================================================================

def test_regenerate_step_sets_feedback(client, sample_mission):
    """Test /regenerate sets regeneration_feedback."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(
        f"/api/missions/{sample_mission.id}/regenerate",
        json={"feedback": "Make it more casual"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "success"
    assert data["feedback_applied"] is True
    assert data["mission_status"] == "PENDING"
    
    app.dependency_overrides.clear()


def test_regenerate_step_without_feedback(client, sample_mission):
    """Test /regenerate works without feedback."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(
        f"/api/missions/{sample_mission.id}/regenerate",
        json={}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["feedback_applied"] is False
    
    app.dependency_overrides.clear()


def test_regenerate_step_rejects_wrong_status(client, sample_mission):
    """Test /regenerate rejects if mission not in AWAITING_APPROVAL."""
    from src.main.db.database import get_db
    
    sample_mission.status = "COMPLETED"  # Wrong status
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(
        f"/api/missions/{sample_mission.id}/regenerate",
        json={"feedback": "test"}
    )
    
    assert response.status_code == 400
    
    app.dependency_overrides.clear()


# =============================================================================
# Tests: POST /api/missions/{mission_id}/skip
# =============================================================================

def test_skip_step_records_agent(client, sample_mission):
    """Test /skip records the skipped agent."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(f"/api/missions/{sample_mission.id}/skip")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "success"
    assert data["skipped_agent"] == "RewriterAgent"
    assert data["current_agent_index"] == 1
    assert "RewriterAgent" in data["skipped_agents"]
    
    app.dependency_overrides.clear()


def test_skip_step_advances_index(client, sample_mission):
    """Test /skip advances to next agent."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 1
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(f"/api/missions/{sample_mission.id}/skip")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["skipped_agent"] == "MarketingAgent"
    assert data["next_agent"] == "PriceScoutAgent"
    
    app.dependency_overrides.clear()


def test_skip_step_completes_at_end(client, sample_mission):
    """Test /skip marks complete at last agent."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 3
    # Add some draft content
    sample_mission.current_state["draft_title"] = "Test Title"
    sample_mission.current_state["draft_content"] = "<p>Test</p>"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    # Mock Shopify save functions (may be called on completion) - patch where they're used
    with patch("src.main.db.db_transactions.get_shop_access_token", return_value="test-token"), \
         patch("src.main.services.shopify_service.save_product_content_with_locale", new_callable=AsyncMock), \
         patch("src.main.services.shopify_service.save_product_metafields", new_callable=AsyncMock):
        
        response = client.post(f"/api/missions/{sample_mission.id}/skip")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["is_complete"] is True
    assert data["skipped_agent"] == "ComplianceAgent"
    
    app.dependency_overrides.clear()


def test_skip_step_allows_pending_status(client, sample_mission):
    """Test /skip also accepts PENDING status (for skipping before run)."""
    from src.main.db.database import get_db
    
    sample_mission.status = "PENDING"
    sample_mission.current_state["status"] = "PENDING"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(f"/api/missions/{sample_mission.id}/skip")
    
    assert response.status_code == 200
    
    app.dependency_overrides.clear()


def test_skip_step_rejects_completed(client, sample_mission):
    """Test /skip rejects if mission already completed."""
    from src.main.db.database import get_db
    
    sample_mission.status = "COMPLETED"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(f"/api/missions/{sample_mission.id}/skip")
    
    assert response.status_code == 400
    
    app.dependency_overrides.clear()


# =============================================================================
# Tests: Mission Creation with Step Mode
# =============================================================================

def test_create_mission_returns_step_info(client):
    """Test POST /api/missions returns step-by-step journey info."""
    from src.main.db.database import get_db
    from src.main.api.validation import validate_shop_and_quota
    
    mock_session = MagicMock()
    
    # Mock validation
    mock_plan = MagicMock()
    mock_plan.name = "Standard"
    
    app.dependency_overrides[get_db] = lambda: mock_session
    app.dependency_overrides[validate_shop_and_quota] = lambda db, shop, enforce_limit: {"plan": mock_plan}
    
    with patch("src.main.api.shopify.missions.validate_shop_and_quota", return_value={"plan": mock_plan}):
        response = client.post(
            "/api/missions",
            json={
                "product_id": "prod-123",
                "product_name": "Test Product",
                "japanese_description": "テスト説明",
            }
        )
    
    assert response.status_code == 200
    data = response.json()
    
    # Step journey info should be present
    assert "workflow_agents" in data
    assert "total_agents" in data
    assert "current_agent_index" in data
    assert "step_url" in data
    assert data["current_agent_index"] == 0
    assert data["first_agent"] is not None
    
    app.dependency_overrides.clear()


# =============================================================================
# Tests: Concurrent Execution Prevention
# =============================================================================

def test_run_step_rejects_if_already_in_progress(client, sample_mission):
    """Test /run-step rejects if step already in progress."""
    from src.main.db.database import get_db
    from src.main.api.shopify.missions import _mission_locks
    
    sample_mission.status = "PENDING"
    
    # Simulate lock being held
    _mission_locks[sample_mission.id] = True
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    # run-step is GET because EventSource only supports GET
    response = client.get(f"/api/missions/{sample_mission.id}/run-step")
    
    assert response.status_code == 409
    assert "already" in response.json()["detail"].lower()
    
    # Clean up lock
    _mission_locks.pop(sample_mission.id, None)
    app.dependency_overrides.clear()


def test_run_step_rejects_completed_mission(client, sample_mission):
    """Test /run-step rejects already completed mission."""
    from src.main.db.database import get_db
    
    sample_mission.status = "COMPLETED"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    # run-step is GET because EventSource only supports GET
    response = client.get(f"/api/missions/{sample_mission.id}/run-step")
    
    assert response.status_code == 400
    assert "completed" in response.json()["detail"].lower()
    
    app.dependency_overrides.clear()


def test_run_step_rejects_error_mission(client, sample_mission):
    """Test /run-step rejects mission in error state."""
    from src.main.db.database import get_db
    
    sample_mission.status = "ERROR"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    # run-step is GET because EventSource only supports GET
    response = client.get(f"/api/missions/{sample_mission.id}/run-step")
    
    assert response.status_code == 400
    assert "error" in response.json()["detail"].lower()
    
    app.dependency_overrides.clear()


# =============================================================================
# Tests: Edge Cases
# =============================================================================

def test_status_with_empty_workflow_agents(client, sample_mission):
    """Test /status handles empty workflow_agents gracefully."""
    from src.main.db.database import get_db
    
    sample_mission.current_state["workflow_agents"] = []
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.get(f"/api/missions/{sample_mission.id}/status")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["total_agents"] == 0
    assert data["current_agent"] is None
    
    app.dependency_overrides.clear()


def test_continue_at_index_zero(client, sample_mission):
    """Test /continue from first agent."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 0
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["current_agent_index"] == 1
    
    app.dependency_overrides.clear()


def test_regenerate_empty_body(client, sample_mission):
    """Test /regenerate accepts completely empty body."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    # Send request with no body at all
    response = client.post(
        f"/api/missions/{sample_mission.id}/regenerate",
        content="",
        headers={"Content-Type": "application/json"}
    )
    
    # Should handle gracefully (empty body defaults to {})
    assert response.status_code in [200, 422]  # Either accept empty or validation error
    
    app.dependency_overrides.clear()


# =============================================================================
# Tests: Shopify Save Integration (verify correct parameters)
# =============================================================================

def test_continue_completion_saves_product_content(client, sample_mission):
    """Test /continue saves product content to Shopify when mission completes."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 3  # Last agent
    sample_mission.current_state["draft_title"] = "Optimized Title"
    sample_mission.current_state["draft_content"] = "<p>Optimized description</p>"
    sample_mission.current_state["product_id"] = "prod-123"
    sample_mission.current_state["target_locale"] = "en"
    sample_mission.current_state["raw_input"] = {
        "primary_locale": "en",
        "product_name": "Original Title"
    }
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    with patch("src.main.db.db_transactions.get_shop_access_token", return_value="test-access-token") as mock_get_token, \
         patch("src.main.services.shopify_service.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.services.shopify_service.save_product_metafields", new_callable=AsyncMock) as mock_save_meta:
        
        response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    assert response.status_code == 200
    
    # Verify save_product_content_with_locale was called with correct args
    mock_save_content.assert_called_once()
    call_kwargs = mock_save_content.call_args.kwargs
    assert call_kwargs["shop_domain"] == "test-shop.myshopify.com"
    assert call_kwargs["access_token"] == "test-access-token"
    assert call_kwargs["product_id"] == "prod-123"
    assert call_kwargs["title"] == "Optimized Title"
    assert call_kwargs["description"] == "<p>Optimized description</p>"
    assert call_kwargs["target_locale"] == "en"
    
    app.dependency_overrides.clear()


def test_continue_completion_saves_metafields(client, sample_mission):
    """Test /continue saves metafields when mission completes with agent data."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 3
    sample_mission.current_state["product_id"] = "prod-456"
    sample_mission.current_state["draft_title"] = "Title"
    sample_mission.current_state["draft_content"] = "Content"
    
    # Add agent data that should be saved as metafields
    sample_mission.current_state["social_hooks"] = [
        {"type": "Story", "caption": "Test caption", "hashtags": ["#test"]}
    ]
    sample_mission.current_state["pricing_analysis"] = {
        "recommended_price": 29.99,
        "confidence": 0.85
    }
    sample_mission.current_state["seo_title"] = "SEO Optimized Title"
    sample_mission.current_state["seo_description"] = "SEO meta description"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    with patch("src.main.db.db_transactions.get_shop_access_token", return_value="token"), \
         patch("src.main.services.shopify_service.save_product_content_with_locale", new_callable=AsyncMock), \
         patch("src.main.services.shopify_service.save_product_metafields", new_callable=AsyncMock) as mock_save_meta:
        
        response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    assert response.status_code == 200
    
    # Verify save_product_metafields was called
    mock_save_meta.assert_called_once()
    call_kwargs = mock_save_meta.call_args.kwargs
    
    # Verify metafields structure
    metafields = call_kwargs["metafields"]
    assert len(metafields) == 3  # social_hooks, pricing_analysis, seo_data
    
    # Check namespaces and keys
    metafield_keys = {mf["key"] for mf in metafields}
    assert "social_hooks" in metafield_keys
    assert "pricing_analysis" in metafield_keys
    assert "seo_data" in metafield_keys
    
    # All should be crossborder_agent namespace
    for mf in metafields:
        assert mf["namespace"] == "crossborder_agent"
        assert mf["type"] == "json"
    
    app.dependency_overrides.clear()


def test_continue_completion_no_save_without_access_token(client, sample_mission):
    """Test /continue skips Shopify save if no access token."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 3
    sample_mission.current_state["draft_title"] = "Title"
    sample_mission.current_state["draft_content"] = "Content"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    # Return None for access token
    with patch("src.main.db.db_transactions.get_shop_access_token", return_value=None), \
         patch("src.main.services.shopify_service.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.services.shopify_service.save_product_metafields", new_callable=AsyncMock) as mock_save_meta:
        
        response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    assert response.status_code == 200
    
    # Save functions should not be called without access token
    mock_save_content.assert_not_called()
    mock_save_meta.assert_not_called()
    
    app.dependency_overrides.clear()


def test_continue_completion_no_save_without_content(client, sample_mission):
    """Test /continue skips product content save if no draft content."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 3
    sample_mission.current_state["product_id"] = "prod-123"
    # No draft_title or draft_content
    sample_mission.current_state["draft_title"] = None
    sample_mission.current_state["draft_content"] = None
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    with patch("src.main.db.db_transactions.get_shop_access_token", return_value="token"), \
         patch("src.main.services.shopify_service.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.services.shopify_service.save_product_metafields", new_callable=AsyncMock) as mock_save_meta:
        
        response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    assert response.status_code == 200
    
    # Product content save should not be called without content
    mock_save_content.assert_not_called()
    # But metafields save should also not be called since there's no data
    mock_save_meta.assert_not_called()
    
    app.dependency_overrides.clear()


def test_continue_completion_handles_shopify_error_gracefully(client, sample_mission):
    """Test /continue handles Shopify save errors gracefully without failing."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 3
    sample_mission.current_state["product_id"] = "prod-123"
    sample_mission.current_state["draft_title"] = "Title"
    sample_mission.current_state["draft_content"] = "Content"
    sample_mission.current_state["raw_input"] = {"primary_locale": "en"}
    sample_mission.current_state["target_locale"] = "en"
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    # Mock save to raise an exception
    mock_save_content = AsyncMock(side_effect=Exception("Shopify API Error"))
    
    with patch("src.main.db.db_transactions.get_shop_access_token", return_value="token"), \
         patch("src.main.services.shopify_service.save_product_content_with_locale", mock_save_content), \
         patch("src.main.services.shopify_service.save_product_metafields", new_callable=AsyncMock):
        
        response = client.post(f"/api/missions/{sample_mission.id}/continue")
    
    # Request should still succeed even if Shopify save failed
    assert response.status_code == 200
    data = response.json()
    assert data["is_complete"] is True
    
    app.dependency_overrides.clear()


def test_skip_completion_saves_to_shopify(client, sample_mission):
    """Test /skip saves to Shopify when mission completes via skip."""
    from src.main.db.database import get_db
    
    sample_mission.status = "AWAITING_APPROVAL"
    sample_mission.current_state["status"] = "AWAITING_APPROVAL"
    sample_mission.current_state["current_agent_index"] = 3  # Last agent
    sample_mission.current_state["product_id"] = "prod-789"
    sample_mission.current_state["draft_title"] = "Title from earlier agent"
    sample_mission.current_state["draft_content"] = "Content from earlier agent"
    sample_mission.current_state["target_locale"] = "en"
    sample_mission.current_state["raw_input"] = {"primary_locale": "en"}
    
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = sample_mission
    
    app.dependency_overrides[get_db] = lambda: mock_session
    
    with patch("src.main.db.db_transactions.get_shop_access_token", return_value="token"), \
         patch("src.main.services.shopify_service.save_product_content_with_locale", new_callable=AsyncMock) as mock_save_content, \
         patch("src.main.services.shopify_service.save_product_metafields", new_callable=AsyncMock):
        
        response = client.post(f"/api/missions/{sample_mission.id}/skip")
    
    assert response.status_code == 200
    data = response.json()
    assert data["is_complete"] is True
    
    # Verify save was called
    mock_save_content.assert_called_once()
    call_kwargs = mock_save_content.call_args.kwargs
    assert call_kwargs["product_id"] == "prod-789"
    
    app.dependency_overrides.clear()

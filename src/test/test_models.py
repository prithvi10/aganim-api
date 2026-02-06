from src.main.api.models import RewriteRequest, MissionRequest
from src.main.config.configs import DEFAULT_PRODUCT_CATEGORY
import pytest

def test_rewrite_request_defaults():
    """Test that default values are applied correctly."""
    request = RewriteRequest(
        product_name="Test Product",
        japanese_description="Test Description"
    )
    assert request.product_name == "Test Product"
    assert request.japanese_description == "Test Description"
    assert request.category == DEFAULT_PRODUCT_CATEGORY

def test_rewrite_request_custom_values():
    """Test that custom values are accepted."""
    request = RewriteRequest(
        product_name="Test Product",
        japanese_description="Test Description",
        category="Specific Category"
    )
    assert request.category == "Specific Category"

def test_rewrite_request_validation():
    """Test that required fields are validated."""
    with pytest.raises(ValueError):
        RewriteRequest(product_name="Missing Description")


# =============================================================================
# Tests: MissionRequest Model
# =============================================================================

class TestMissionRequest:
    """Tests for MissionRequest model including ad-hoc agent selection."""
    
    def test_mission_request_defaults(self):
        """Test that default values are applied correctly."""
        request = MissionRequest(
            product_id="prod-123",
            product_name="Test Product",
            japanese_description="日本語の説明"
        )
        assert request.product_id == "prod-123"
        assert request.product_name == "Test Product"
        assert request.japanese_description == "日本語の説明"
        assert request.category == "General"
        assert request.target_locale == "en"
        assert request.tone_profile == "professional"
        assert request.brand_soul_enabled is False
        assert request.requested_agents is None

    def test_mission_request_with_requested_agents(self):
        """Test that requested_agents field accepts a list of agents."""
        request = MissionRequest(
            product_id="prod-123",
            product_name="Test Product",
            japanese_description="日本語の説明",
            requested_agents=["CopywriterAgent"]
        )
        assert request.requested_agents == ["CopywriterAgent"]

    def test_mission_request_with_multiple_requested_agents(self):
        """Test that requested_agents can contain multiple agents."""
        request = MissionRequest(
            product_id="prod-123",
            product_name="Test Product",
            japanese_description="日本語の説明",
            requested_agents=["MarketingAgent", "ComplianceAgent"]
        )
        assert request.requested_agents == ["MarketingAgent", "ComplianceAgent"]
        assert len(request.requested_agents) == 2

    def test_mission_request_with_all_agents(self):
        """Test that requested_agents can contain all agents."""
        all_agents = ["CopywriterAgent", "MarketingAgent", "PriceScoutAgent", "ComplianceAgent"]
        request = MissionRequest(
            product_id="prod-123",
            product_name="Test Product",
            japanese_description="日本語の説明",
            requested_agents=all_agents
        )
        assert request.requested_agents == all_agents
        assert len(request.requested_agents) == 4

    def test_mission_request_with_empty_requested_agents(self):
        """Test that requested_agents can be an empty list."""
        request = MissionRequest(
            product_id="prod-123",
            product_name="Test Product",
            japanese_description="日本語の説明",
            requested_agents=[]
        )
        assert request.requested_agents == []

    def test_mission_request_custom_tone_profile(self):
        """Test that custom tone profiles are accepted."""
        request = MissionRequest(
            product_id="prod-123",
            product_name="Test Product",
            japanese_description="日本語の説明",
            tone_profile="luxury"
        )
        assert request.tone_profile == "luxury"

    def test_mission_request_all_fields(self):
        """Test MissionRequest with all fields specified."""
        request = MissionRequest(
            product_id="prod-456",
            product_name="Premium Bowl",
            japanese_description="高級な陶器ボウル",
            category="Kitchenware",
            target_locale="zh-TW",
            tone_profile="minimalist",
            brand_soul_enabled=True,
            requested_agents=["CopywriterAgent", "MarketingAgent"]
        )
        assert request.product_id == "prod-456"
        assert request.product_name == "Premium Bowl"
        assert request.category == "Kitchenware"
        assert request.target_locale == "zh-TW"
        assert request.tone_profile == "minimalist"
        assert request.brand_soul_enabled is True
        assert request.requested_agents == ["CopywriterAgent", "MarketingAgent"]

    def test_mission_request_validation_missing_product_id(self):
        """Test that product_id is required."""
        with pytest.raises(ValueError):
            MissionRequest(
                product_name="Test Product",
                japanese_description="日本語の説明"
            )

    def test_mission_request_validation_missing_product_name(self):
        """Test that product_name is required."""
        with pytest.raises(ValueError):
            MissionRequest(
                product_id="prod-123",
                japanese_description="日本語の説明"
            )

    def test_mission_request_validation_missing_description(self):
        """Test that japanese_description is required."""
        with pytest.raises(ValueError):
            MissionRequest(
                product_id="prod-123",
                product_name="Test Product"
            )
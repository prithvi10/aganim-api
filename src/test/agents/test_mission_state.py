"""
Unit tests for MissionState and AgentContext dataclasses.

Tests serialization, deserialization, and helper methods.
"""

import pytest
from unittest.mock import MagicMock

from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext, AgentPlan, AgentAction


# =============================================================================
# Tests: MissionState
# =============================================================================

class TestMissionState:
    """Tests for MissionState dataclass."""

    def test_mission_state_initialization(self):
        """Test basic MissionState initialization."""
        state = MissionState(
            product_id="test-123",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={"title": "Test Product"},
        )
        
        assert state.product_id == "test-123"
        assert state.shop_id == "test-shop.myshopify.com"
        assert state.plan_tier == "Standard"
        assert state.status == "PENDING"

    def test_mission_state_default_values(self):
        """Test MissionState default values."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Basic",
            raw_input={},
        )
        
        assert state.draft_content is None
        assert state.draft_title is None
        assert state.compliance_flags == []
        assert state.logs == []
        assert state.error_message is None

    def test_add_log(self):
        """Test add_log method."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Basic",
            raw_input={},
        )
        
        state.add_log("Test log message")
        
        assert len(state.logs) == 1
        assert "Test log message" in state.logs[0]

    def test_add_log_multiple(self):
        """Test multiple add_log calls."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Basic",
            raw_input={},
        )
        
        state.add_log("Log 1")
        state.add_log("Log 2")
        state.add_log("Log 3")
        
        assert len(state.logs) == 3

    def test_set_error(self):
        """Test set_error method."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Basic",
            raw_input={},
        )
        
        state.set_error("Test error message")
        
        assert state.status == "ERROR"
        assert state.error_message == "Test error message"
        assert "ERROR: Test error message" in state.logs

    def test_to_dict(self):
        """Test to_dict serialization."""
        state = MissionState(
            product_id="test-123",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={"title": "Test Product"},
        )
        state.draft_content = "Test content"
        state.draft_title = "Test Title"
        
        result = state.to_dict()
        
        assert isinstance(result, dict)
        assert result["product_id"] == "test-123"
        assert result["shop_id"] == "test-shop.myshopify.com"
        assert result["draft_content"] == "Test content"
        assert result["draft_title"] == "Test Title"

    def test_from_dict(self):
        """Test from_dict deserialization."""
        data = {
            "product_id": "test-123",
            "shop_id": "test-shop.myshopify.com",
            "plan_tier": "Standard",
            "raw_input": {"title": "Test Product"},
            "draft_content": "Test content",
            "status": "COMPLETED",
        }
        
        state = MissionState.from_dict(data)
        
        assert state.product_id == "test-123"
        assert state.draft_content == "Test content"
        assert state.status == "COMPLETED"

    def test_roundtrip_serialization(self):
        """Test that to_dict and from_dict are inverse operations."""
        original = MissionState(
            product_id="test-123",
            shop_id="test-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={"title": "Test", "description": "Desc"},
            target_locale="en",
        )
        original.draft_content = "Content"
        original.seo_title = "SEO Title"
        original.add_log("Test log")
        
        # Roundtrip
        data = original.to_dict()
        restored = MissionState.from_dict(data)
        
        assert restored.product_id == original.product_id
        assert restored.draft_content == original.draft_content
        assert restored.seo_title == original.seo_title

    def test_marketing_fields(self):
        """Test marketing-related fields."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        
        # Set marketing fields
        state.seo_title = "SEO Title"
        state.seo_description = "SEO Description"
        state.seo_alt_text = "Alt text"
        state.seo_insights = {"lsi_keywords_used": ["keyword1"]}
        state.seo_recommendations = {"competitive_edge": "test"}
        state.ctr_check = {"score": 0.75}
        state.serp_insights = [{"title": "Competitor"}]
        
        result = state.to_dict()
        
        assert result["seo_title"] == "SEO Title"
        assert result["seo_description"] == "SEO Description"
        assert result["ctr_check"]["score"] == 0.75


# =============================================================================
# Tests: AgentContext
# =============================================================================

class TestAgentContext:
    """Tests for AgentContext dataclass."""

    def test_agent_context_initialization(self):
        """Test basic AgentContext initialization."""
        context = AgentContext(
            raw_input={"title": "Test Product", "description": "Test desc"},
        )
        
        assert context.raw_input["title"] == "Test Product"

    def test_get_product_title(self):
        """Test get_product_title helper."""
        context = AgentContext(
            raw_input={"title": "Test Product", "description": "Test"},
        )
        
        assert context.get_product_title() == "Test Product"

    def test_get_product_title_fallback(self):
        """Test get_product_title with product_name fallback."""
        context = AgentContext(
            raw_input={"product_name": "Fallback Name", "description": "Test"},
        )
        
        assert context.get_product_title() == "Fallback Name"

    def test_get_product_description(self):
        """Test get_product_description helper."""
        context = AgentContext(
            raw_input={"title": "Test", "description": "Test Description"},
        )
        
        assert context.get_product_description() == "Test Description"

    def test_get_product_description_fallback(self):
        """Test get_product_description with japanese_description fallback."""
        context = AgentContext(
            raw_input={"title": "Test", "japanese_description": "日本語の説明"},
        )
        
        assert context.get_product_description() == "日本語の説明"

    def test_get_category(self):
        """Test get_category helper."""
        context = AgentContext(
            raw_input={"title": "Test", "category": "Kitchenware"},
        )
        
        assert context.get_category() == "Kitchenware"

    def test_get_category_default(self):
        """Test get_category default value."""
        context = AgentContext(
            raw_input={"title": "Test"},
        )
        
        # Should return "General" as default
        assert context.get_category() == "General"

    def test_get_brand_context_text(self):
        """Test get_brand_context_text formatting."""
        context = AgentContext(
            raw_input={"title": "Test"},
            brand_context=[
                {"content": "We are a Kyoto atelier."},
                {"content": "Focus on quality craftsmanship."},
            ],
        )
        
        text = context.get_brand_context_text()
        
        assert "Kyoto atelier" in text
        assert "quality craftsmanship" in text

    def test_get_learned_rules_text(self):
        """Test get_learned_rules_text formatting."""
        context = AgentContext(
            raw_input={"title": "Test"},
            learned_rules=[
                {"rule": "Use formal tone"},
                {"rule": "Keep descriptions concise"},
            ],
        )
        
        text = context.get_learned_rules_text()
        
        assert "formal tone" in text
        assert "concise" in text


# =============================================================================
# Tests: AgentPlan
# =============================================================================

class TestAgentPlan:
    """Tests for AgentPlan dataclass."""

    def test_agent_plan_initialization(self):
        """Test basic AgentPlan initialization."""
        plan = AgentPlan(
            steps=["step1", "step2"],
            selected_tools=["tool1", "tool2"],
            confidence=0.9,
            reasoning="Test reasoning",
        )
        
        assert len(plan.steps) == 2
        assert plan.confidence == 0.9

    def test_agent_plan_confidence_clamping_high(self):
        """Test that confidence is clamped when too high."""
        plan = AgentPlan(
            steps=["step1"],
            selected_tools=["tool1"],
            confidence=1.5,
            reasoning="Test",
        )
        
        assert plan.confidence == 1.0

    def test_agent_plan_confidence_clamping_low(self):
        """Test that confidence is clamped when too low."""
        plan = AgentPlan(
            steps=["step1"],
            selected_tools=["tool1"],
            confidence=-0.5,
            reasoning="Test",
        )
        
        assert plan.confidence == 0.0


# =============================================================================
# Tests: AgentAction
# =============================================================================

class TestAgentAction:
    """Tests for AgentAction dataclass."""

    def test_agent_action_success_factory(self):
        """Test AgentAction.success_action factory."""
        action = AgentAction.success_action(
            tool_name="test.tool",
            output="test output",
            input_params={"key": "value"},
        )
        
        assert action.tool_name == "test.tool"
        assert action.output == "test output"
        assert action.success is True
        assert action.error is None

    def test_agent_action_failure_factory(self):
        """Test AgentAction.failure_action factory."""
        action = AgentAction.failure_action(
            tool_name="test.tool",
            error="Test error",
            input_params={"key": "value"},
        )
        
        assert action.tool_name == "test.tool"
        assert action.output is None
        assert action.success is False
        assert action.error == "Test error"

    def test_agent_action_to_dict(self):
        """Test AgentAction.to_dict serialization."""
        action = AgentAction.success_action(
            tool_name="test.tool",
            output="test output",
        )
        
        result = action.to_dict()
        
        assert isinstance(result, dict)
        assert result["tool_name"] == "test.tool"
        assert result["success"] is True

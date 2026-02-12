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

    # =========================================================================
    # Tests: Step-by-Step Journey Fields
    # =========================================================================

    def test_step_journey_default_values(self):
        """Test step journey fields have correct defaults."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        
        assert state.current_agent_index == 0
        assert state.skipped_agents == []
        assert state.agent_outputs == {}
        assert state.regeneration_feedback is None
        assert state.workflow_agents == []

    def test_step_journey_fields_to_dict(self):
        """Test step journey fields are serialized correctly."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        
        state.current_agent_index = 2
        state.skipped_agents = ["MarketingAgent"]
        state.agent_outputs = {"CopywriterAgent": {"draft_title": "Test"}}
        state.regeneration_feedback = "Make it shorter"
        state.workflow_agents = ["CopywriterAgent", "MarketingAgent", "PriceScoutAgent"]
        
        result = state.to_dict()
        
        assert result["current_agent_index"] == 2
        assert result["skipped_agents"] == ["MarketingAgent"]
        assert result["agent_outputs"]["CopywriterAgent"]["draft_title"] == "Test"
        assert result["regeneration_feedback"] == "Make it shorter"
        assert len(result["workflow_agents"]) == 3

    def test_step_journey_fields_from_dict(self):
        """Test step journey fields are deserialized correctly."""
        data = {
            "product_id": "test",
            "shop_id": "test-shop",
            "plan_tier": "Standard",
            "raw_input": {},
            "current_agent_index": 3,
            "skipped_agents": ["CopywriterAgent", "PriceScoutAgent"],
            "agent_outputs": {
                "MarketingAgent": {"seo_title": "Test SEO"}
            },
            "regeneration_feedback": "More formal tone",
            "workflow_agents": ["A", "B", "C", "D"],
        }
        
        state = MissionState.from_dict(data)
        
        assert state.current_agent_index == 3
        assert len(state.skipped_agents) == 2
        assert "CopywriterAgent" in state.skipped_agents
        assert state.agent_outputs["MarketingAgent"]["seo_title"] == "Test SEO"
        assert state.regeneration_feedback == "More formal tone"
        assert len(state.workflow_agents) == 4

    def test_step_journey_roundtrip(self):
        """Test step journey fields survive roundtrip serialization."""
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        
        original.current_agent_index = 2
        original.skipped_agents = ["Agent1"]
        original.agent_outputs = {"Agent0": {"output": "data"}}
        original.regeneration_feedback = "feedback"
        original.workflow_agents = ["Agent0", "Agent1", "Agent2"]
        
        data = original.to_dict()
        restored = MissionState.from_dict(data)
        
        assert restored.current_agent_index == original.current_agent_index
        assert restored.skipped_agents == original.skipped_agents
        assert restored.agent_outputs == original.agent_outputs
        assert restored.regeneration_feedback == original.regeneration_feedback
        assert restored.workflow_agents == original.workflow_agents

    def test_awaiting_approval_status(self):
        """Test AWAITING_APPROVAL status is valid."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        
        state.status = "AWAITING_APPROVAL"
        
        result = state.to_dict()
        assert result["status"] == "AWAITING_APPROVAL"
        
        restored = MissionState.from_dict(result)
        assert restored.status == "AWAITING_APPROVAL"

    # =========================================================================
    # Tests: workflow_config (Mission Architect)
    # =========================================================================

    def test_workflow_config_default_empty(self):
        """Test workflow_config defaults to empty list."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        
        assert state.workflow_config == []

    def test_workflow_config_to_dict(self):
        """Test workflow_config is serialized correctly."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        
        state.workflow_config = [
            {"agent_name": "RewriterAgent", "has_gate": True},
            {"agent_name": "SEOAgent", "has_gate": False},
            {"agent_name": "PriceScoutAgent", "has_gate": True},
        ]
        
        result = state.to_dict()
        
        assert "workflow_config" in result
        assert len(result["workflow_config"]) == 3
        assert result["workflow_config"][0]["agent_name"] == "RewriterAgent"
        assert result["workflow_config"][0]["has_gate"] is True
        assert result["workflow_config"][1]["agent_name"] == "SEOAgent"
        assert result["workflow_config"][1]["has_gate"] is False

    def test_workflow_config_from_dict(self):
        """Test workflow_config is deserialized correctly."""
        data = {
            "product_id": "test",
            "shop_id": "test-shop",
            "plan_tier": "Standard",
            "raw_input": {},
            "workflow_config": [
                {"agent_name": "PriceScoutAgent", "has_gate": True},
                {"agent_name": "MarketingAgent", "has_gate": False},
            ],
        }
        
        state = MissionState.from_dict(data)
        
        assert len(state.workflow_config) == 2
        assert state.workflow_config[0]["agent_name"] == "PriceScoutAgent"
        assert state.workflow_config[0]["has_gate"] is True
        assert state.workflow_config[1]["agent_name"] == "MarketingAgent"
        assert state.workflow_config[1]["has_gate"] is False

    def test_workflow_config_from_dict_missing_defaults_empty(self):
        """Test workflow_config defaults to empty list when missing from dict."""
        data = {
            "product_id": "test",
            "shop_id": "test-shop",
            "plan_tier": "Standard",
            "raw_input": {},
        }
        
        state = MissionState.from_dict(data)
        
        assert state.workflow_config == []

    def test_workflow_config_roundtrip(self):
        """Test workflow_config survives roundtrip serialization."""
        config = [
            {"agent_name": "RewriterAgent", "has_gate": True},
            {"agent_name": "SEOAgent", "has_gate": False},
            {"agent_name": "MarketingAgent", "has_gate": True},
            {"agent_name": "PriceScoutAgent", "has_gate": False},
        ]
        
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        original.workflow_config = config
        
        data = original.to_dict()
        restored = MissionState.from_dict(data)
        
        assert restored.workflow_config == original.workflow_config
        assert len(restored.workflow_config) == 4
        assert restored.workflow_config[1]["has_gate"] is False
        assert restored.workflow_config[2]["has_gate"] is True

    def test_workflow_config_with_all_fields_roundtrip(self):
        """Test workflow_config serializes alongside all other step journey fields."""
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={"title": "Test"},
        )
        original.current_agent_index = 2
        original.workflow_agents = ["RewriterAgent", "SEOAgent", "MarketingAgent"]
        original.workflow_config = [
            {"agent_name": "RewriterAgent", "has_gate": True},
            {"agent_name": "SEOAgent", "has_gate": False},
            {"agent_name": "MarketingAgent", "has_gate": True},
        ]
        original.agent_outputs = {"RewriterAgent": {"draft_title": "Title"}}
        original.skipped_agents = ["SEOAgent"]
        
        data = original.to_dict()
        restored = MissionState.from_dict(data)
        
        assert restored.current_agent_index == 2
        assert restored.workflow_agents == original.workflow_agents
        assert restored.workflow_config == original.workflow_config
        assert restored.agent_outputs == original.agent_outputs
        assert restored.skipped_agents == original.skipped_agents

    def test_multiple_agent_outputs(self):
        """Test storing outputs from multiple agents."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        
        state.agent_outputs = {
            "CopywriterAgent": {
                "draft_content": "Content 1",
                "draft_title": "Title 1",
            },
            "MarketingAgent": {
                "seo_title": "SEO Title",
                "ctr_check": {"score": 0.85},
            },
            "PriceScoutAgent": {
                "pricing_analysis": {"recommended_price": 29.99},
            },
            "ComplianceAgent": {
                "compliance_flags": [],
            },
        }
        
        result = state.to_dict()
        
        assert len(result["agent_outputs"]) == 4
        assert result["agent_outputs"]["CopywriterAgent"]["draft_title"] == "Title 1"
        assert result["agent_outputs"]["MarketingAgent"]["ctr_check"]["score"] == 0.85
        assert result["agent_outputs"]["PriceScoutAgent"]["pricing_analysis"]["recommended_price"] == 29.99
        assert result["agent_outputs"]["ComplianceAgent"]["compliance_flags"] == []

    # =========================================================================
    # Tests: Autonomous Execution Fields
    # =========================================================================

    def test_autonomous_defaults_false(self):
        """Test that autonomous defaults to False."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Standard",
            raw_input={},
        )
        assert state.autonomous is False

    def test_autonomous_can_be_set_true(self):
        """Test that autonomous can be explicitly set to True."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
            autonomous=True,
        )
        assert state.autonomous is True

    def test_autonomous_to_dict(self):
        """Test that autonomous is serialized in to_dict."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
            autonomous=True,
        )
        result = state.to_dict()
        assert "autonomous" in result
        assert result["autonomous"] is True

    def test_autonomous_to_dict_false(self):
        """Test that autonomous=False is serialized in to_dict."""
        state = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Basic",
            raw_input={},
        )
        result = state.to_dict()
        assert result["autonomous"] is False

    def test_autonomous_from_dict_true(self):
        """Test that autonomous=True survives from_dict deserialization."""
        data = {
            "product_id": "test",
            "shop_id": "test-shop",
            "plan_tier": "Pro",
            "raw_input": {},
            "autonomous": True,
        }
        state = MissionState.from_dict(data)
        assert state.autonomous is True

    def test_autonomous_from_dict_missing_defaults_false(self):
        """Test that autonomous defaults to False when missing from dict."""
        data = {
            "product_id": "test",
            "shop_id": "test-shop",
            "plan_tier": "Standard",
            "raw_input": {},
        }
        state = MissionState.from_dict(data)
        assert state.autonomous is False

    def test_autonomous_roundtrip(self):
        """Test that autonomous survives roundtrip serialization."""
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={},
            autonomous=True,
        )
        data = original.to_dict()
        restored = MissionState.from_dict(data)
        assert restored.autonomous is True

    def test_autonomous_with_all_fields_roundtrip(self):
        """Test that autonomous co-exists with all other fields during roundtrip."""
        original = MissionState(
            product_id="test",
            shop_id="test-shop",
            plan_tier="Pro",
            raw_input={"title": "Test"},
            autonomous=True,
        )
        original.current_agent_index = 1
        original.workflow_config = [
            {"agent_name": "RewriterAgent", "has_gate": True},
            {"agent_name": "SEOAgent", "has_gate": False},
        ]
        original.workflow_agents = ["RewriterAgent", "SEOAgent"]
        original.draft_content = "Content"

        data = original.to_dict()
        restored = MissionState.from_dict(data)

        assert restored.autonomous is True
        assert restored.current_agent_index == 1
        assert len(restored.workflow_config) == 2
        assert restored.draft_content == "Content"


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

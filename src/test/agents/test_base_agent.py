"""
Unit tests for BaseAgent class.

Tests the 4-phase agentic loop: Perception → Reasoning → Action → Feedback
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Tuple

from src.main.agents.base import BaseAgent
from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext, AgentPlan, AgentAction


# =============================================================================
# Test Agent Implementation (minimal concrete implementation for testing)
# =============================================================================

class MockAgent(BaseAgent):
    """Minimal agent implementation for testing BaseAgent functionality."""
    
    role_name = "MockAgent"
    default_tool = "test.tool"
    
    def __init__(self, shop_id: str, services, simulate_error: bool = False):
        super().__init__(shop_id, services)
        self.simulate_error = simulate_error
        self.perceive_called = False
        self.act_called = False
        self.feedback_called = False
    
    async def _perceive_domain(
        self,
        state: MissionState,
        context: AgentContext,
    ) -> AgentContext:
        """Add domain-specific perception."""
        self.perceive_called = True
        context.external_data["perceived"] = True
        return context
    
    async def _act_domain(
        self,
        state: MissionState,
        context: AgentContext,
        plan: AgentPlan,
    ) -> Tuple[List[AgentAction], MissionState]:
        """Execute domain-specific action."""
        self.act_called = True
        
        if self.simulate_error:
            raise Exception("Simulated error")
        
        actions = [
            AgentAction.success_action(
                tool_name="test.tool",
                output="test output",
                input_params={"test": True},
            )
        ]
        state.draft_content = "Test draft content"
        return actions, state

    async def _feedback_domain(
        self,
        old_state: MissionState,
        new_state: MissionState,
        actions: List[AgentAction],
    ) -> None:
        """Record domain-specific feedback."""
        self.feedback_called = True


class MockAgentWithLLMReasoning(MockAgent):
    """Agent that requires LLM-based reasoning."""
    requires_llm_reasoning = True


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for testing."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value='{"title": "Test"}')
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=[])
    return services


@pytest.fixture
def mission_state():
    """Create a basic MissionState for testing."""
    return MissionState(
        product_id="test-product-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Basic",
        raw_input={
            "title": "Test Product",
            "description": "Test description",
            "category": "Test Category",
        },
    )


# =============================================================================
# Tests: 4-Phase Loop Execution
# =============================================================================

@pytest.mark.asyncio
async def test_run_executes_all_phases(mock_services, mission_state):
    """Test that run() executes all 4 phases: perceive, reason, act, feedback."""
    agent = MockAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Verify all phases were called
    assert agent.perceive_called is True
    assert agent.act_called is True
    assert agent.feedback_called is True
    
    # Verify state was updated
    assert result.draft_content == "Test draft content"
    assert len(result.logs) > 0


@pytest.mark.asyncio
async def test_run_logs_each_phase(mock_services, mission_state):
    """Test that run() adds log entries for each phase."""
    agent = MockAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Check log entries
    log_text = "\n".join(result.logs)
    assert "Perceiving" in log_text
    assert "Planning" in log_text
    assert "Executing" in log_text
    assert "Completed" in log_text


# =============================================================================
# Tests: Error Handling
# =============================================================================

@pytest.mark.asyncio
async def test_run_handles_error_gracefully(mock_services, mission_state):
    """Test that errors during execution set error state."""
    agent = MockAgent("test-shop.myshopify.com", mock_services, simulate_error=True)
    
    result = await agent.run(mission_state)
    
    # Should not raise, but set error state
    assert result.status == "ERROR"
    assert result.error_message is not None
    assert "MockAgent failed" in result.error_message
    assert "Simulated error" in result.error_message


@pytest.mark.asyncio
async def test_set_error_updates_state(mission_state):
    """Test that set_error() properly updates state."""
    mission_state.set_error("Test error message")
    
    assert mission_state.status == "ERROR"
    assert mission_state.error_message == "Test error message"
    assert "ERROR: Test error message" in mission_state.logs


# =============================================================================
# Tests: Deterministic vs LLM Reasoning
# =============================================================================

@pytest.mark.asyncio
async def test_default_reasoning_is_deterministic(mock_services, mission_state):
    """Test that default reasoning uses deterministic plan (no LLM call)."""
    agent = MockAgent("test-shop.myshopify.com", mock_services)
    
    context = AgentContext(raw_input=mission_state.raw_input)
    plan = await agent.reason(mission_state, context)
    
    # Should return a valid plan
    assert plan is not None
    assert plan.steps == ["execute_primary_action"]
    assert plan.selected_tools == ["test.tool"]
    assert plan.confidence == 1.0
    
    # Should NOT call LLM
    mock_services.llm.generate_text.assert_not_called()
    mock_services.llm.generate_structured.assert_not_called()


@pytest.mark.asyncio
async def test_llm_reasoning_when_enabled(mock_services, mission_state):
    """Test that LLM reasoning is used when requires_llm_reasoning=True."""
    agent = MockAgentWithLLMReasoning("test-shop.myshopify.com", mock_services)
    
    # Override _reason_with_llm to track if it's called
    agent._reason_with_llm = AsyncMock(return_value=AgentPlan(
        steps=["step1", "step2"],
        selected_tools=["tool1", "tool2"],
        confidence=0.9,
        reasoning="LLM reasoning",
    ))
    
    context = AgentContext(raw_input=mission_state.raw_input)
    plan = await agent.reason(mission_state, context)
    
    # Should call _reason_with_llm
    agent._reason_with_llm.assert_called_once()
    assert plan.reasoning == "LLM reasoning"


# =============================================================================
# Tests: AgentAction Factories
# =============================================================================

def test_agent_action_success_factory():
    """Test AgentAction.success_action() factory method."""
    action = AgentAction.success_action(
        tool_name="test.tool",
        output="test output",
        input_params={"param": "value"},
    )
    
    assert action.tool_name == "test.tool"
    assert action.output == "test output"
    assert action.input_params == {"param": "value"}
    assert action.success is True
    assert action.error is None


def test_agent_action_failure_factory():
    """Test AgentAction.failure_action() factory method."""
    action = AgentAction.failure_action(
        tool_name="test.tool",
        error="Test error message",
        input_params={"param": "value"},
    )
    
    assert action.tool_name == "test.tool"
    assert action.output is None
    assert action.input_params == {"param": "value"}
    assert action.success is False
    assert action.error == "Test error message"


def test_agent_action_to_dict():
    """Test AgentAction.to_dict() serialization."""
    action = AgentAction.success_action(
        tool_name="test.tool",
        output="test output",
        input_params={"param": "value"},
    )
    
    result = action.to_dict()
    
    assert result["tool_name"] == "test.tool"
    assert result["success"] is True
    assert result["error"] is None


# =============================================================================
# Tests: Perception Phase
# =============================================================================

@pytest.mark.asyncio
async def test_perceive_gathers_learned_rules(mock_services, mission_state):
    """Test that perceive() fetches learned preferences from memory."""
    agent = MockAgent("test-shop.myshopify.com", mock_services)
    
    # Mock memory service
    agent.memory.get_learned_preferences = AsyncMock(return_value=[
        {"rule": "User prefers formal tone"},
        {"rule": "Keep descriptions under 100 words"},
    ])
    
    context = await agent.perceive(mission_state)
    
    # Should have learned rules
    assert len(context.learned_rules) == 2
    assert context.learned_rules[0]["rule"] == "User prefers formal tone"
    
    # Should call memory service
    agent.memory.get_learned_preferences.assert_called_once_with("MockAgent")


@pytest.mark.asyncio
async def test_perceive_calls_domain_perceive(mock_services, mission_state):
    """Test that perceive() calls _perceive_domain()."""
    agent = MockAgent("test-shop.myshopify.com", mock_services)
    
    context = await agent.perceive(mission_state)
    
    # Domain-specific perception should have run
    assert context.external_data.get("perceived") is True


# =============================================================================
# Tests: Feedback Phase
# =============================================================================

@pytest.mark.asyncio
async def test_feedback_records_failures(mock_services, mission_state):
    """Test that feedback() records failed actions to memory."""
    agent = MockAgent("test-shop.myshopify.com", mock_services)
    
    # Mock memory service
    agent.memory.record_failure = AsyncMock()
    
    actions = [
        AgentAction.failure_action(
            tool_name="test.tool",
            error="Test error",
        )
    ]
    
    await agent.feedback(mission_state, mission_state, actions)
    
    # Should record failure
    agent.memory.record_failure.assert_called_once_with(
        "MockAgent",
        "test.tool",
        "Test error",
    )


@pytest.mark.asyncio
async def test_feedback_calls_domain_feedback(mock_services, mission_state):
    """Test that feedback() calls _feedback_domain()."""
    agent = MockAgent("test-shop.myshopify.com", mock_services)
    
    actions = [AgentAction.success_action("test", "output")]
    
    await agent.feedback(mission_state, mission_state, actions)
    
    # Domain-specific feedback should have run
    assert agent.feedback_called is True


# =============================================================================
# Tests: AgentPlan Validation
# =============================================================================

def test_agent_plan_confidence_clamping():
    """Test that AgentPlan clamps confidence to valid range."""
    # Too high
    plan = AgentPlan(
        steps=["step1"],
        selected_tools=["tool1"],
        confidence=1.5,
        reasoning="test",
    )
    assert plan.confidence == 1.0
    
    # Too low
    plan = AgentPlan(
        steps=["step1"],
        selected_tools=["tool1"],
        confidence=-0.5,
        reasoning="test",
    )
    assert plan.confidence == 0.0
    
    # Valid
    plan = AgentPlan(
        steps=["step1"],
        selected_tools=["tool1"],
        confidence=0.75,
        reasoning="test",
    )
    assert plan.confidence == 0.75

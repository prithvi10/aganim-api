"""
Unit and integration tests for MissionControl orchestrator.

Tests workflow building, sequential execution, adversarial loops, and state streaming.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.main.agents.orchestrator import MissionControl, run_mission
from src.main.agents.state import MissionState
from src.main.agents.copywriter import CopywriterAgent
from src.main.agents.marketing import MarketingAgent
from src.main.agents.price_scout import PriceScoutAgent
from src.main.agents.compliance import ComplianceAgent
from src.main.services import ServiceRegistry


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for testing."""
    services = MagicMock()  # No spec so we can freely add attributes
    
    # Mock LLM responses
    services.llm.generate_text = AsyncMock(return_value='{"title": "Test", "description": "Test desc"}')
    services.llm.generate_structured = AsyncMock(return_value=MagicMock(
        model_dump=lambda: {"has_violations": False, "flags": [], "severity": "none"},
        has_violations=False,
        flags=[],
        severity="none",
    ))
    services.llm.generate_json = AsyncMock(return_value={})
    
    # Mock SERP
    services.serp.search = AsyncMock(return_value=[])
    services.serp.get_competitor_prices = AsyncMock(return_value=[])
    
    # Mock RAG
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mission_state():
    """Create a basic MissionState for testing."""
    return MissionState(
        product_id="test-product-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Standard",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "description": "Made in Kyoto using traditional techniques.",
            "category": "Kitchenware",
        },
        target_locale="en",
    )


# =============================================================================
# Tests: Workflow Building
# =============================================================================

def test_build_workflow_free_tier(mock_services):
    """Test that Free tier gets full agent workflow."""
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Free tier should have all agents (full pipeline available to all)
    assert CopywriterAgent in mission.workflow
    assert MarketingAgent in mission.workflow
    assert PriceScoutAgent in mission.workflow
    assert ComplianceAgent in mission.workflow


def test_build_workflow_basic_tier(mock_services):
    """Test that Basic tier gets full agent workflow."""
    mission = MissionControl(
        plan_tier="Basic",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Basic tier should have all agents
    assert CopywriterAgent in mission.workflow
    assert MarketingAgent in mission.workflow


def test_build_workflow_standard_tier(mock_services):
    """Test that Standard tier gets full agent workflow."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Standard tier should have all agents
    assert len(mission.workflow) == 4


def test_build_workflow_pro_tier(mock_services):
    """Test that Pro tier gets full agent workflow."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Pro tier should have all agents
    assert len(mission.workflow) == 4


def test_build_workflow_unknown_tier_defaults(mock_services):
    """Test that unknown tier defaults to Copywriter only."""
    mission = MissionControl(
        plan_tier="Unknown",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Unknown tier should default to just Copywriter
    assert mission.workflow == [CopywriterAgent]


# =============================================================================
# Tests: Sequential Execution
# =============================================================================

@pytest.mark.asyncio
async def test_execute_runs_all_agents(mock_services, mission_state):
    """Test that execute runs all agents in workflow."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Should yield state after initial + each agent + final
    # At minimum: 1 initial + N agents + 1 final = N+2
    assert len(states) >= 2
    
    # Final state should be COMPLETED or COMPLIANCE_REVIEW
    assert states[-1].status in ["COMPLETED", "COMPLIANCE_REVIEW"]


@pytest.mark.asyncio
async def test_execute_yields_state_after_each_agent(mock_services, mission_state):
    """Test that execute yields state updates after each agent."""
    mission = MissionControl(
        plan_tier="Basic",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Check that logs show each agent running
    all_logs = "\n".join(["\n".join(s.logs) for s in states])
    assert "Copywriter" in all_logs or "Marketing" in all_logs


@pytest.mark.asyncio
async def test_execute_stops_on_error(mock_services, mission_state):
    """Test that execute stops early when error occurs."""
    # Make first agent set error status
    async def mock_fail_run(self, state):
        state.status = "ERROR"
        state.error_message = "Test error"
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_fail_run):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # Should have stopped after error
        final_state = states[-1]
        assert final_state.status == "ERROR"


# =============================================================================
# Tests: Adversarial Loop
# =============================================================================

@pytest.mark.asyncio
async def test_adversarial_loop_triggers_on_compliance_flags(mock_services, mission_state):
    """Test that adversarial loop triggers when compliance flags are present."""
    mission_state.plan_tier = "Pro"
    
    # Make compliance agent return flags first time
    call_count = [0]
    
    async def mock_compliance_run(self, state):
        call_count[0] += 1
        if call_count[0] == 1:
            state.compliance_flags = ["FDA violation"]
            state.status = "COMPLIANCE_REVIEW"
        else:
            state.compliance_flags = []
        return state
    
    with patch.object(ComplianceAgent, 'run', mock_compliance_run), \
         patch.object(CopywriterAgent, 'run', new_callable=AsyncMock) as mock_copy, \
         patch.object(MarketingAgent, 'run', new_callable=AsyncMock) as mock_market, \
         patch.object(PriceScoutAgent, 'run', new_callable=AsyncMock) as mock_price:
        
        # Set up mocks to pass through state
        mock_copy.return_value = mission_state
        mock_copy.side_effect = lambda s: s
        mock_market.return_value = mission_state
        mock_market.side_effect = lambda s: s
        mock_price.return_value = mission_state
        mock_price.side_effect = lambda s: s
        
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # Should have triggered adversarial loop
        all_logs = "\n".join(["\n".join(s.logs) for s in states])
        assert "Adversarial" in all_logs


@pytest.mark.asyncio
async def test_adversarial_loop_limits_iterations(mock_services, mission_state):
    """Test that adversarial loop is limited to MAX_ADVERSARIAL_ITERATIONS."""
    mission_state.plan_tier = "Pro"
    
    # Track iterations
    iteration_count = [0]
    
    # Make compliance always fail
    async def mock_compliance_run(self, state):
        state.compliance_flags = ["Persistent violation"]
        state.status = "COMPLIANCE_REVIEW"
        return state
    
    async def mock_copywriter_run(self, state):
        iteration_count[0] += 1
        return state
    
    async def mock_pass_through(self, state):
        return state
    
    with patch.object(ComplianceAgent, 'run', mock_compliance_run), \
         patch.object(CopywriterAgent, 'run', mock_copywriter_run), \
         patch.object(MarketingAgent, 'run', mock_pass_through), \
         patch.object(PriceScoutAgent, 'run', mock_pass_through):
        
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # Copywriter runs once normally + MAX_ADVERSARIAL_ITERATIONS times in loop
        expected_max = 1 + MissionControl.MAX_ADVERSARIAL_ITERATIONS
        assert iteration_count[0] <= expected_max


@pytest.mark.asyncio
async def test_adversarial_loop_passes_compliance_feedback(mock_services, mission_state):
    """Test that compliance feedback is passed to copywriter in adversarial loop."""
    mission_state.plan_tier = "Pro"
    call_count = [0]
    
    async def mock_compliance_run(self, state):
        call_count[0] += 1
        if call_count[0] == 1:
            state.compliance_flags = ["Remove health claims"]
        else:
            state.compliance_flags = []
        return state
    
    received_feedback = [None]
    
    async def mock_copywriter_run(self, state):
        # Check if compliance feedback was added
        if "compliance_feedback" in state.raw_input:
            received_feedback[0] = state.raw_input["compliance_feedback"]
        return state
    
    async def mock_pass_through(self, state):
        return state
    
    with patch.object(ComplianceAgent, 'run', mock_compliance_run), \
         patch.object(CopywriterAgent, 'run', mock_copywriter_run), \
         patch.object(MarketingAgent, 'run', mock_pass_through), \
         patch.object(PriceScoutAgent, 'run', mock_pass_through):
        
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        async for _ in mission.execute(mission_state):
            pass
        
        # Should have received compliance feedback
        assert received_feedback[0] is not None
        assert "health claims" in received_feedback[0]


# =============================================================================
# Tests: Execute Single Agent
# =============================================================================

@pytest.mark.asyncio
async def test_execute_single_agent(mock_services, mission_state):
    """Test execute_single_agent utility method."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Execute single copywriter agent
    result = await mission.execute_single_agent(CopywriterAgent, mission_state)
    
    # Should return updated state
    assert result is not None


# =============================================================================
# Tests: Workflow Info
# =============================================================================

def test_get_workflow_info(mock_services):
    """Test get_workflow_info method."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    info = mission.get_workflow_info()
    
    assert info["plan_tier"] == "Pro"
    assert info["shop_id"] == "test-shop.myshopify.com"
    assert info["agent_count"] == 4
    assert "mission_id" in info


# =============================================================================
# Tests: State Streaming
# =============================================================================

@pytest.mark.asyncio
async def test_execute_streams_status_updates(mock_services, mission_state):
    """Test that execute streams status updates."""
    async def mock_pass_through(self, state):
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through), \
         patch.object(MarketingAgent, 'run', mock_pass_through), \
         patch.object(PriceScoutAgent, 'run', mock_pass_through), \
         patch.object(ComplianceAgent, 'run', mock_pass_through):
        
        mission = MissionControl(
            plan_tier="Basic",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        statuses = []
        async for state in mission.execute(mission_state):
            states.append(state)
            statuses.append(state.status)
        
        # Should have IN_PROGRESS at some point
        assert "IN_PROGRESS" in statuses
        
        # Last state should be COMPLETED
        assert states[-1].status == "COMPLETED"


# =============================================================================
# Tests: run_mission Convenience Function
# =============================================================================

@pytest.mark.asyncio
async def test_run_mission_convenience_function():
    """Test the run_mission convenience function."""
    with patch('src.main.agents.orchestrator.ServiceRegistry') as MockRegistry, \
         patch.object(MissionControl, 'execute') as mock_execute:
        
        # Mock execute to return async generator
        async def mock_gen():
            state = MissionState(
                product_id="test",
                shop_id="test-shop",
                plan_tier="Basic",
                raw_input={},
            )
            state.status = "COMPLETED"
            yield state
        
        mock_execute.return_value = mock_gen()
        MockRegistry.create_default.return_value = MagicMock()
        
        states = []
        async for state in run_mission(
            shop_id="test-shop.myshopify.com",
            product_data={"title": "Test", "description": "Test"},
            plan_tier="Basic",
        ):
            states.append(state)
        
        # Should have at least one state
        assert len(states) >= 1


# =============================================================================
# Tests: Error Handling
# =============================================================================

@pytest.mark.asyncio
async def test_execute_handles_exception(mock_services, mission_state):
    """Test that execute handles exceptions gracefully."""
    async def mock_fail(self, state):
        raise Exception("Agent crashed")
    
    with patch.object(CopywriterAgent, 'run', mock_fail):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # Should have error state
        final_state = states[-1]
        assert final_state.status == "ERROR"
        assert "Workflow error" in final_state.error_message

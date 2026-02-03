"""
Unit and integration tests for MissionControl orchestrator.

Tests workflow building, sequential execution, adversarial loops, and state streaming.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.main.agents.orchestrator import MissionControl, run_mission, AGENT_MAP
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
# Tests: AGENT_MAP Configuration
# =============================================================================

def test_agent_map_contains_all_agents():
    """Test that AGENT_MAP contains all expected agent classes."""
    assert "CopywriterAgent" in AGENT_MAP
    assert "MarketingAgent" in AGENT_MAP
    assert "PriceScoutAgent" in AGENT_MAP
    assert "ComplianceAgent" in AGENT_MAP
    assert len(AGENT_MAP) == 4


def test_agent_map_maps_to_correct_classes():
    """Test that AGENT_MAP maps names to correct agent classes."""
    assert AGENT_MAP["CopywriterAgent"] == CopywriterAgent
    assert AGENT_MAP["MarketingAgent"] == MarketingAgent
    assert AGENT_MAP["PriceScoutAgent"] == PriceScoutAgent
    assert AGENT_MAP["ComplianceAgent"] == ComplianceAgent


# =============================================================================
# Tests: Ad-hoc Agent Selection
# =============================================================================

def test_adhoc_single_agent_copywriter(mock_services):
    """Test ad-hoc mode with single CopywriterAgent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["CopywriterAgent"],
    )
    
    assert len(mission.workflow) == 1
    assert CopywriterAgent in mission.workflow


def test_adhoc_single_agent_marketing(mock_services):
    """Test ad-hoc mode with single MarketingAgent."""
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["MarketingAgent"],
    )
    
    assert len(mission.workflow) == 1
    assert MarketingAgent in mission.workflow


def test_adhoc_single_agent_price_scout(mock_services):
    """Test ad-hoc mode with single PriceScoutAgent."""
    mission = MissionControl(
        plan_tier="Basic",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["PriceScoutAgent"],
    )
    
    assert len(mission.workflow) == 1
    assert PriceScoutAgent in mission.workflow


def test_adhoc_single_agent_compliance(mock_services):
    """Test ad-hoc mode with single ComplianceAgent."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["ComplianceAgent"],
    )
    
    assert len(mission.workflow) == 1
    assert ComplianceAgent in mission.workflow


def test_adhoc_multiple_agents(mock_services):
    """Test ad-hoc mode with multiple agents."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["MarketingAgent", "ComplianceAgent"],
    )
    
    assert len(mission.workflow) == 2
    assert MarketingAgent in mission.workflow
    assert ComplianceAgent in mission.workflow


def test_adhoc_all_agents(mock_services):
    """Test ad-hoc mode with all agents."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["CopywriterAgent", "MarketingAgent", "PriceScoutAgent", "ComplianceAgent"],
    )
    
    assert len(mission.workflow) == 4


def test_adhoc_preserves_order(mock_services):
    """Test that ad-hoc mode preserves agent order."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["ComplianceAgent", "CopywriterAgent"],
    )
    
    # Should preserve order: Compliance first, then Copywriter
    assert mission.workflow[0] == ComplianceAgent
    assert mission.workflow[1] == CopywriterAgent


def test_adhoc_unknown_agent_skipped(mock_services):
    """Test that unknown agent names are skipped."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["CopywriterAgent", "UnknownAgent", "MarketingAgent"],
    )
    
    # UnknownAgent should be skipped
    assert len(mission.workflow) == 2
    assert CopywriterAgent in mission.workflow
    assert MarketingAgent in mission.workflow


def test_adhoc_all_unknown_falls_back_to_tier(mock_services):
    """Test that if all requested agents are unknown, fall back to tier workflow."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["UnknownAgent1", "UnknownAgent2"],
    )
    
    # Should fall back to Standard tier workflow (all 4 agents)
    assert len(mission.workflow) == 4


def test_adhoc_empty_list_uses_tier_workflow(mock_services):
    """Test that empty requested_agents list uses tier workflow."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=[],
    )
    
    # Empty list should trigger fallback to tier workflow
    assert len(mission.workflow) == 4


def test_adhoc_none_uses_tier_workflow(mock_services):
    """Test that None requested_agents uses tier workflow."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=None,
    )
    
    # None should use tier-based workflow
    assert len(mission.workflow) == 4


def test_adhoc_overrides_tier_workflow(mock_services):
    """Test that ad-hoc mode completely overrides tier workflow."""
    # Free tier normally gets all 4 agents
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["ComplianceAgent"],
    )
    
    # Ad-hoc should override to just one agent
    assert len(mission.workflow) == 1
    assert mission.workflow == [ComplianceAgent]


# =============================================================================
# Tests: Workflow Info with Ad-hoc
# =============================================================================

def test_get_workflow_info_adhoc(mock_services):
    """Test get_workflow_info includes ad-hoc information."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["CopywriterAgent"],
    )
    
    info = mission.get_workflow_info()
    
    assert info["is_adhoc"] is True
    assert info["requested_agents"] == ["CopywriterAgent"]
    assert info["agent_count"] == 1


def test_get_workflow_info_not_adhoc(mock_services):
    """Test get_workflow_info when not in ad-hoc mode."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    info = mission.get_workflow_info()
    
    assert info["is_adhoc"] is False
    assert info["requested_agents"] is None


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


@pytest.mark.asyncio
async def test_run_mission_with_requested_agents():
    """Test the run_mission convenience function with ad-hoc agents."""
    with patch('src.main.agents.orchestrator.ServiceRegistry') as MockRegistry, \
         patch.object(MissionControl, '__init__', return_value=None) as mock_init, \
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
            requested_agents=["MarketingAgent"],
        ):
            states.append(state)
        
        # Verify MissionControl was called with requested_agents
        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args.kwargs
        assert call_kwargs.get("requested_agents") == ["MarketingAgent"]


# =============================================================================
# Tests: Ad-hoc Execution
# =============================================================================

@pytest.mark.asyncio
async def test_adhoc_execute_runs_only_requested_agents(mock_services, mission_state):
    """Test that ad-hoc mode only runs the requested agents."""
    async def mock_pass_through(self, state):
        state.add_log(f"{self.role_name}: Executed")
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through), \
         patch.object(MarketingAgent, 'run', mock_pass_through), \
         patch.object(PriceScoutAgent, 'run', mock_pass_through), \
         patch.object(ComplianceAgent, 'run', mock_pass_through):
        
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            requested_agents=["ComplianceAgent"],
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # Check that only ComplianceAgent ran
        all_logs = "\n".join(["\n".join(s.logs) for s in states])
        assert "Compliance" in all_logs
        # Copywriter and others should not have run
        assert "Copywriter: Executed" not in all_logs
        assert "Marketing: Executed" not in all_logs
        assert "PriceScout: Executed" not in all_logs


@pytest.mark.asyncio
async def test_adhoc_execute_runs_multiple_requested_agents(mock_services, mission_state):
    """Test that ad-hoc mode runs multiple requested agents."""
    async def mock_pass_through(self, state):
        state.add_log(f"{self.role_name}: Executed")
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through), \
         patch.object(MarketingAgent, 'run', mock_pass_through), \
         patch.object(PriceScoutAgent, 'run', mock_pass_through), \
         patch.object(ComplianceAgent, 'run', mock_pass_through):
        
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            requested_agents=["MarketingAgent", "PriceScoutAgent"],
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # Check that both requested agents ran
        all_logs = "\n".join(["\n".join(s.logs) for s in states])
        assert "Marketing" in all_logs
        assert "PriceScout" in all_logs


@pytest.mark.asyncio
async def test_adhoc_no_adversarial_loop_without_compliance(mock_services, mission_state):
    """Test that adversarial loop doesn't trigger without ComplianceAgent."""
    mission_state.plan_tier = "Pro"
    
    async def mock_pass_through(self, state):
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through), \
         patch.object(MarketingAgent, 'run', mock_pass_through):
        
        # Ad-hoc without ComplianceAgent
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            requested_agents=["CopywriterAgent", "MarketingAgent"],
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # No adversarial loop should trigger
        all_logs = "\n".join(["\n".join(s.logs) for s in states])
        assert "Adversarial" not in all_logs


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


# =============================================================================
# Tests: Step-by-Step Journey - execute_single_step
# =============================================================================

@pytest.mark.asyncio
async def test_execute_single_step_runs_first_agent(mock_services, mission_state):
    """Test that execute_single_step runs only the first agent."""
    async def mock_pass_through(self, state):
        state.add_log(f"{self.role_name}: Executed")
        state.draft_content = "Test content"
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        # Should have run first agent only
        final_state = states[-1]
        assert final_state.status == "AWAITING_APPROVAL"
        assert "Copywriter" in "\n".join(final_state.logs)


@pytest.mark.asyncio
async def test_execute_single_step_sets_workflow_agents(mock_services, mission_state):
    """Test that execute_single_step populates workflow_agents in state."""
    async def mock_pass_through(self, state):
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert len(final_state.workflow_agents) == 4
        assert "CopywriterAgent" in final_state.workflow_agents


@pytest.mark.asyncio
async def test_execute_single_step_stores_agent_output(mock_services, mission_state):
    """Test that execute_single_step stores agent output separately."""
    async def mock_pass_through(self, state):
        state.draft_content = "Generated content"
        state.draft_title = "Generated title"
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert "CopywriterAgent" in final_state.agent_outputs
        assert final_state.agent_outputs["CopywriterAgent"]["draft_content"] == "Generated content"


@pytest.mark.asyncio
async def test_execute_single_step_with_regeneration_feedback(mock_services, mission_state):
    """Test that execute_single_step injects regeneration feedback."""
    received_feedback = [None]
    
    async def mock_check_feedback(self, state):
        if "_regeneration_feedback" in state.raw_input:
            received_feedback[0] = state.raw_input["_regeneration_feedback"]
        return state
    
    with patch.object(CopywriterAgent, 'run', mock_check_feedback):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        mission_state.regeneration_feedback = "Make it more casual"
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        # Feedback should have been injected
        assert received_feedback[0] == "Make it more casual"
        # Feedback should be cleared after use
        assert states[-1].regeneration_feedback is None


@pytest.mark.asyncio
async def test_execute_single_step_completes_at_end(mock_services, mission_state):
    """Test that execute_single_step marks COMPLETED when at end of workflow."""
    async def mock_pass_through(self, state):
        return state
    
    with patch.object(ComplianceAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        # Set to last agent index
        mission_state.current_agent_index = 4  # Beyond last
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert final_state.status == "COMPLETED"


@pytest.mark.asyncio
async def test_execute_single_step_handles_error(mock_services, mission_state):
    """Test that execute_single_step handles agent errors."""
    async def mock_fail(self, state):
        raise Exception("Agent crashed")
    
    with patch.object(CopywriterAgent, 'run', mock_fail):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert final_state.status == "ERROR"
        assert "crashed" in final_state.error_message


# =============================================================================
# Tests: Step-by-Step Journey - advance_to_next_step
# =============================================================================

def test_advance_to_next_step_increments_index(mock_services, mission_state):
    """Test that advance_to_next_step increments current_agent_index."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 0
    mission_state.workflow_agents = ["CopywriterAgent", "MarketingAgent"]
    
    result = mission.advance_to_next_step(mission_state)
    
    assert result.current_agent_index == 1
    assert result.status == "PENDING"


def test_advance_to_next_step_logs_next_agent(mock_services, mission_state):
    """Test that advance_to_next_step logs the next agent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 0
    mission_state.workflow_agents = ["CopywriterAgent", "MarketingAgent"]
    
    result = mission.advance_to_next_step(mission_state)
    
    assert "MarketingAgent" in "\n".join(result.logs)


def test_advance_to_next_step_completes_at_end(mock_services, mission_state):
    """Test that advance_to_next_step marks COMPLETED at end."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 3  # Last agent
    mission_state.workflow_agents = ["A", "B", "C", "D"]
    
    result = mission.advance_to_next_step(mission_state)
    
    assert result.current_agent_index == 4
    assert result.status == "COMPLETED"


# =============================================================================
# Tests: Step-by-Step Journey - skip_current_step
# =============================================================================

def test_skip_current_step_records_skipped_agent(mock_services, mission_state):
    """Test that skip_current_step records the skipped agent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 1
    mission_state.workflow_agents = ["CopywriterAgent", "MarketingAgent", "PriceScoutAgent"]
    
    result = mission.skip_current_step(mission_state)
    
    assert "MarketingAgent" in result.skipped_agents
    assert result.current_agent_index == 2


def test_skip_current_step_logs_skip(mock_services, mission_state):
    """Test that skip_current_step logs the skip action."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 0
    mission_state.workflow_agents = ["CopywriterAgent", "MarketingAgent"]
    
    result = mission.skip_current_step(mission_state)
    
    assert "Skipped" in "\n".join(result.logs)


def test_skip_current_step_completes_at_end(mock_services, mission_state):
    """Test that skip_current_step marks COMPLETED at end."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 3  # Last agent index (0-based)
    # Use actual agent names that match the workflow
    mission_state.workflow_agents = ["CopywriterAgent", "MarketingAgent", "PriceScoutAgent", "ComplianceAgent"]
    
    result = mission.skip_current_step(mission_state)
    
    assert result.status == "COMPLETED"
    assert "ComplianceAgent" in result.skipped_agents


def test_skip_current_step_preserves_previous_skips(mock_services, mission_state):
    """Test that skip_current_step preserves previously skipped agents."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 2  # PriceScoutAgent
    mission_state.workflow_agents = ["CopywriterAgent", "MarketingAgent", "PriceScoutAgent", "ComplianceAgent"]
    mission_state.skipped_agents = ["CopywriterAgent"]  # Previously skipped
    
    result = mission.skip_current_step(mission_state)
    
    assert "CopywriterAgent" in result.skipped_agents  # Preserved
    assert "PriceScoutAgent" in result.skipped_agents  # Newly skipped
    assert len(result.skipped_agents) == 2


# =============================================================================
# Tests: Step-by-Step Journey - prepare_regeneration
# =============================================================================

def test_prepare_regeneration_sets_feedback(mock_services, mission_state):
    """Test that prepare_regeneration sets regeneration_feedback."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 0
    mission_state.workflow_agents = ["CopywriterAgent"]
    
    result = mission.prepare_regeneration(mission_state, feedback="Make it shorter")
    
    assert result.regeneration_feedback == "Make it shorter"
    assert result.status == "PENDING"


def test_prepare_regeneration_without_feedback(mock_services, mission_state):
    """Test that prepare_regeneration works without feedback."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 0
    mission_state.workflow_agents = ["CopywriterAgent"]
    
    result = mission.prepare_regeneration(mission_state)
    
    assert result.regeneration_feedback is None
    assert result.status == "PENDING"


def test_prepare_regeneration_logs_action(mock_services, mission_state):
    """Test that prepare_regeneration logs the action."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 1
    mission_state.workflow_agents = ["CopywriterAgent", "MarketingAgent"]
    
    result = mission.prepare_regeneration(mission_state, feedback="test")
    
    assert "regenerate" in "\n".join(result.logs).lower()


# =============================================================================
# Tests: Step-by-Step Journey - _extract_agent_output
# =============================================================================

def test_extract_agent_output_copywriter(mock_services, mission_state):
    """Test _extract_agent_output for CopywriterAgent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.draft_content = "Test content"
    mission_state.draft_title = "Test title"
    mission_state.discovered_values = [{"name": "quality", "value": "high"}]
    
    output = mission._extract_agent_output(mission_state, "CopywriterAgent")
    
    assert output["draft_content"] == "Test content"
    assert output["draft_title"] == "Test title"
    assert len(output["discovered_values"]) == 1


def test_extract_agent_output_marketing(mock_services, mission_state):
    """Test _extract_agent_output for MarketingAgent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.seo_title = "SEO Title"
    mission_state.seo_description = "SEO Desc"
    mission_state.ctr_check = {"score": 0.8}
    mission_state.serp_insights = [{"title": "Competitor"}]
    
    output = mission._extract_agent_output(mission_state, "MarketingAgent")
    
    assert output["seo_title"] == "SEO Title"
    assert output["seo_description"] == "SEO Desc"
    assert output["ctr_check"]["score"] == 0.8


def test_extract_agent_output_price_scout(mock_services, mission_state):
    """Test _extract_agent_output for PriceScoutAgent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.pricing_analysis = {
        "recommended_price": 29.99,
        "confidence": 0.85,
    }
    
    output = mission._extract_agent_output(mission_state, "PriceScoutAgent")
    
    assert output["pricing_analysis"]["recommended_price"] == 29.99


def test_extract_agent_output_compliance(mock_services, mission_state):
    """Test _extract_agent_output for ComplianceAgent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.compliance_flags = ["FDA violation", "Missing disclosure"]
    
    output = mission._extract_agent_output(mission_state, "ComplianceAgent")
    
    assert len(output["compliance_flags"]) == 2
    assert "FDA violation" in output["compliance_flags"]


def test_extract_agent_output_unknown_agent(mock_services, mission_state):
    """Test _extract_agent_output for unknown agent returns empty dict."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    output = mission._extract_agent_output(mission_state, "UnknownAgent")
    
    assert output == {}

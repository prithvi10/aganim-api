"""
Unit and integration tests for MissionControl orchestrator.

Tests workflow building, sequential execution, and state streaming.
Note: ComplianceAgent is currently disabled, adversarial loop tests are skipped.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.orchestrator import MissionControl, run_mission, AGENT_MAP
from src.ecommerce.state import MissionState
from src.ecommerce.agents.rewriter import RewriterAgent
from src.ecommerce.agents.seo import SEOAgent
from src.ecommerce.agents.marketing import MarketingAgent
from src.ecommerce.agents.price_scout import PriceScoutAgent
from src.ecommerce.services import ServiceRegistry

# Backward compat alias
CopywriterAgent = RewriterAgent


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
    """Test that Free tier gets full agent workflow (4 agents, no Compliance)."""
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Free tier should have 4 agents (Copywriter, SEO, Marketing, PriceScout)
    assert len(mission.workflow) == 4
    assert CopywriterAgent in mission.workflow
    assert SEOAgent in mission.workflow
    assert MarketingAgent in mission.workflow
    assert PriceScoutAgent in mission.workflow


def test_build_workflow_basic_tier(mock_services):
    """Test that Basic tier gets full agent workflow."""
    mission = MissionControl(
        plan_tier="Basic",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Basic tier should have 4 agents
    assert len(mission.workflow) == 4
    assert CopywriterAgent in mission.workflow
    assert SEOAgent in mission.workflow


def test_build_workflow_standard_tier(mock_services):
    """Test that Standard tier gets full agent workflow."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Standard tier should have 4 agents
    assert len(mission.workflow) == 4


def test_build_workflow_pro_tier(mock_services):
    """Test that Pro tier gets full agent workflow."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    # Pro tier should have 6 agents (includes ImageRefinementAgent + VisualMarketingAgent)
    assert len(mission.workflow) == 6


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

def test_agent_map_contains_expected_agents():
    """Test that AGENT_MAP contains expected agent classes (no Compliance)."""
    assert "RewriterAgent" in AGENT_MAP
    assert "CopywriterAgent" in AGENT_MAP  # Backward compat alias
    assert "SEOAgent" in AGENT_MAP
    assert "MarketingAgent" in AGENT_MAP
    assert "PriceScoutAgent" in AGENT_MAP
    assert "VisualAgent" in AGENT_MAP
    assert "ContentHeroAgent" in AGENT_MAP
    # ComplianceAgent should NOT be in AGENT_MAP (disabled)
    # 9 entries: Rewriter, Copywriter(alias), SEO, Marketing, PriceScout, ImageRefinement, VisualMarketing, Visual(compat), ContentHero
    assert len(AGENT_MAP) == 9


def test_agent_map_maps_to_correct_classes():
    """Test that AGENT_MAP maps names to correct agent classes."""
    assert AGENT_MAP["RewriterAgent"] == RewriterAgent
    assert AGENT_MAP["CopywriterAgent"] == RewriterAgent  # Alias
    assert AGENT_MAP["SEOAgent"] == SEOAgent
    assert AGENT_MAP["MarketingAgent"] == MarketingAgent
    assert AGENT_MAP["PriceScoutAgent"] == PriceScoutAgent


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


def test_adhoc_single_agent_seo(mock_services):
    """Test ad-hoc mode with single SEOAgent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["SEOAgent"],
    )
    
    assert len(mission.workflow) == 1
    assert SEOAgent in mission.workflow


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


def test_adhoc_multiple_agents(mock_services):
    """Test ad-hoc mode with multiple agents."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["MarketingAgent", "PriceScoutAgent"],
    )
    
    assert len(mission.workflow) == 2
    assert MarketingAgent in mission.workflow
    assert PriceScoutAgent in mission.workflow


def test_adhoc_all_agents(mock_services):
    """Test ad-hoc mode with all agents."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["CopywriterAgent", "SEOAgent", "MarketingAgent", "PriceScoutAgent"],
    )
    
    assert len(mission.workflow) == 4


def test_adhoc_preserves_order(mock_services):
    """Test that ad-hoc mode preserves agent order."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["PriceScoutAgent", "CopywriterAgent"],
    )
    
    # Should preserve order: PriceScout first, then Copywriter
    assert mission.workflow[0] == PriceScoutAgent
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
    
    # Should fall back to Standard tier workflow (4 agents)
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
    
    # None should use tier-based workflow (Pro = 6 agents)
    assert len(mission.workflow) == 6


def test_adhoc_overrides_tier_workflow(mock_services):
    """Test that ad-hoc mode completely overrides tier workflow."""
    # Free tier normally gets 4 agents
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["SEOAgent"],
    )
    
    # Ad-hoc should override to just one agent
    assert len(mission.workflow) == 1
    assert mission.workflow == [SEOAgent]


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
    
    # Final state should be COMPLETED
    assert states[-1].status == "COMPLETED"


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
    assert "Copywriter" in all_logs or "SEO" in all_logs or "Marketing" in all_logs


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
    assert info["agent_count"] == 6
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
         patch.object(SEOAgent, 'run', mock_pass_through), \
         patch.object(MarketingAgent, 'run', mock_pass_through), \
         patch.object(PriceScoutAgent, 'run', mock_pass_through):
        
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
    with patch('src.ecommerce.orchestrator.ServiceRegistry') as MockRegistry, \
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
    with patch('src.ecommerce.orchestrator.ServiceRegistry') as MockRegistry, \
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
            requested_agents=["SEOAgent"],
        ):
            states.append(state)
        
        # Verify MissionControl was called with requested_agents
        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args.kwargs
        assert call_kwargs.get("requested_agents") == ["SEOAgent"]


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
         patch.object(SEOAgent, 'run', mock_pass_through), \
         patch.object(MarketingAgent, 'run', mock_pass_through), \
         patch.object(PriceScoutAgent, 'run', mock_pass_through):
        
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            requested_agents=["SEOAgent"],
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # Check that only SEOAgent ran
        all_logs = "\n".join(["\n".join(s.logs) for s in states])
        assert "SEO" in all_logs
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
         patch.object(SEOAgent, 'run', mock_pass_through), \
         patch.object(MarketingAgent, 'run', mock_pass_through), \
         patch.object(PriceScoutAgent, 'run', mock_pass_through):
        
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            requested_agents=["SEOAgent", "PriceScoutAgent"],
        )
        
        states = []
        async for state in mission.execute(mission_state):
            states.append(state)
        
        # Check that both requested agents ran
        all_logs = "\n".join(["\n".join(s.logs) for s in states])
        assert "SEO" in all_logs
        assert "PriceScout" in all_logs


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
        assert "Rewriter" in "\n".join(final_state.logs)


@pytest.mark.asyncio
async def test_execute_single_step_sets_workflow_agents(mock_services, mission_state):
    """Test that execute_single_step populates workflow_agents in state."""
    async def mock_pass_through(self, state):
        return state
    
    with patch.object(RewriterAgent, 'run', mock_pass_through):
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
        assert "RewriterAgent" in final_state.workflow_agents


@pytest.mark.asyncio
async def test_execute_single_step_stores_agent_output(mock_services, mission_state):
    """Test that execute_single_step stores agent output separately."""
    async def mock_pass_through(self, state):
        state.draft_content = "Generated content"
        state.draft_title = "Generated title"
        return state
    
    with patch.object(RewriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert "RewriterAgent" in final_state.agent_outputs
        assert final_state.agent_outputs["RewriterAgent"]["draft_content"] == "Generated content"


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
    
    with patch.object(PriceScoutAgent, 'run', mock_pass_through):
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

@pytest.mark.asyncio
async def test_advance_to_next_step_increments_index(mock_services, mission_state):
    """Test that advance_to_next_step increments current_agent_index."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 0
    mission_state.workflow_agents = ["CopywriterAgent", "SEOAgent", "MarketingAgent", "PriceScoutAgent"]
    
    result = await mission.advance_to_next_step(mission_state)
    
    assert result.current_agent_index == 1
    assert result.status == "PENDING"


@pytest.mark.asyncio
async def test_advance_to_next_step_logs_next_agent(mock_services, mission_state):
    """Test that advance_to_next_step logs the next agent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 0
    mission_state.workflow_agents = ["CopywriterAgent", "SEOAgent", "MarketingAgent", "PriceScoutAgent"]
    
    result = await mission.advance_to_next_step(mission_state)
    
    assert "SEOAgent" in "\n".join(result.logs)


@pytest.mark.asyncio
async def test_advance_to_next_step_completes_at_end(mock_services, mission_state):
    """Test that advance_to_next_step marks COMPLETED at end."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 3  # Last agent
    mission_state.workflow_agents = ["CopywriterAgent", "SEOAgent", "MarketingAgent", "PriceScoutAgent"]
    
    result = await mission.advance_to_next_step(mission_state)
    
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
    mission_state.workflow_agents = ["CopywriterAgent", "SEOAgent", "MarketingAgent", "PriceScoutAgent"]
    
    result = mission.skip_current_step(mission_state)
    
    assert "SEOAgent" in result.skipped_agents
    assert result.current_agent_index == 2


def test_skip_current_step_logs_skip(mock_services, mission_state):
    """Test that skip_current_step logs the skip action."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 0
    mission_state.workflow_agents = ["CopywriterAgent", "SEOAgent", "MarketingAgent", "PriceScoutAgent"]
    
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
    mission_state.workflow_agents = ["CopywriterAgent", "SEOAgent", "MarketingAgent", "PriceScoutAgent"]
    
    result = mission.skip_current_step(mission_state)
    
    assert result.status == "COMPLETED"
    assert "PriceScoutAgent" in result.skipped_agents


def test_skip_current_step_preserves_previous_skips(mock_services, mission_state):
    """Test that skip_current_step preserves previously skipped agents."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.current_agent_index = 2  # MarketingAgent
    mission_state.workflow_agents = ["CopywriterAgent", "SEOAgent", "MarketingAgent", "PriceScoutAgent"]
    mission_state.skipped_agents = ["CopywriterAgent"]  # Previously skipped
    
    result = mission.skip_current_step(mission_state)
    
    assert "CopywriterAgent" in result.skipped_agents  # Preserved
    assert "MarketingAgent" in result.skipped_agents  # Newly skipped
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
    mission_state.workflow_agents = ["CopywriterAgent", "SEOAgent"]
    
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


def test_extract_agent_output_seo(mock_services, mission_state):
    """Test _extract_agent_output for SEOAgent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.seo_title = "SEO Title"
    mission_state.seo_description = "SEO Desc"
    mission_state.seo_alt_text = "Alt text"
    mission_state.ctr_check = {"score": 0.8}
    mission_state.serp_insights = [{"title": "Competitor"}]
    
    output = mission._extract_agent_output(mission_state, "SEOAgent")
    
    assert output["seo_title"] == "SEO Title"
    assert output["seo_description"] == "SEO Desc"
    assert output["seo_alt_text"] == "Alt text"
    assert output["ctr_check"]["score"] == 0.8


def test_extract_agent_output_marketing(mock_services, mission_state):
    """Test _extract_agent_output for MarketingAgent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    mission_state.social_hooks = [{"type": "Aesthetic", "caption": "Test"}]
    mission_state.seasonal_campaign = {"holiday": "Christmas"}
    
    output = mission._extract_agent_output(mission_state, "MarketingAgent")
    
    assert len(output["social_hooks"]) == 1
    assert output["seasonal_campaign"]["holiday"] == "Christmas"


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


def test_extract_agent_output_unknown_agent(mock_services, mission_state):
    """Test _extract_agent_output for unknown agent returns empty dict."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    output = mission._extract_agent_output(mission_state, "UnknownAgent")
    
    assert output == {}


# =============================================================================
# Tests: workflow_config (Mission Architect)
# =============================================================================

def test_workflow_config_builds_custom_workflow(mock_services):
    """Test that workflow_config builds a custom agent workflow."""
    config = [
        {"agent_name": "PriceScoutAgent", "has_gate": True},
        {"agent_name": "RewriterAgent", "has_gate": False},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    
    assert len(mission.workflow) == 2
    assert mission.workflow[0] == PriceScoutAgent
    assert mission.workflow[1] == RewriterAgent


def test_workflow_config_preserves_order(mock_services):
    """Test that workflow_config preserves agent order."""
    config = [
        {"agent_name": "MarketingAgent", "has_gate": False},
        {"agent_name": "SEOAgent", "has_gate": True},
        {"agent_name": "RewriterAgent", "has_gate": False},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    
    assert mission.workflow == [MarketingAgent, SEOAgent, RewriterAgent]


def test_workflow_config_overrides_requested_agents(mock_services):
    """Test that workflow_config takes priority over requested_agents."""
    config = [
        {"agent_name": "PriceScoutAgent", "has_gate": True},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        requested_agents=["MarketingAgent", "SEOAgent"],
        workflow_config=config,
    )
    
    # workflow_config should override requested_agents
    assert len(mission.workflow) == 1
    assert mission.workflow[0] == PriceScoutAgent


def test_workflow_config_overrides_tier_workflow(mock_services):
    """Test that workflow_config overrides tier-based workflow."""
    config = [
        {"agent_name": "SEOAgent", "has_gate": True},
    ]
    mission = MissionControl(
        plan_tier="Pro",  # Pro normally gets 4 agents
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    
    assert len(mission.workflow) == 1
    assert mission.workflow[0] == SEOAgent


def test_workflow_config_skips_unknown_agents(mock_services):
    """Test that unknown agents in workflow_config are skipped."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True},
        {"agent_name": "FakeAgent", "has_gate": False},
        {"agent_name": "SEOAgent", "has_gate": True},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    
    assert len(mission.workflow) == 2
    assert mission.workflow[0] == RewriterAgent
    assert mission.workflow[1] == SEOAgent


def test_workflow_config_all_unknown_falls_back(mock_services):
    """Test that all-unknown workflow_config falls back to tier workflow."""
    config = [
        {"agent_name": "FakeAgent1", "has_gate": True},
        {"agent_name": "FakeAgent2", "has_gate": False},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    
    # Should fall back to Standard tier (4 agents)
    assert len(mission.workflow) == 4


def test_workflow_config_empty_list_uses_tier(mock_services):
    """Test that empty workflow_config list uses tier workflow."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=[],
    )
    
    assert len(mission.workflow) == 4


def test_workflow_config_none_uses_tier(mock_services):
    """Test that None workflow_config uses tier workflow."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=None,
    )
    
    assert len(mission.workflow) == 4


def test_workflow_config_backward_compat_alias(mock_services):
    """Test that CopywriterAgent alias works in workflow_config."""
    config = [
        {"agent_name": "CopywriterAgent", "has_gate": True},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    
    assert len(mission.workflow) == 1
    assert mission.workflow[0] == CopywriterAgent  # Which is RewriterAgent


def test_workflow_config_single_agent_no_gate(mock_services):
    """Test workflow_config with single ungated agent."""
    config = [
        {"agent_name": "PriceScoutAgent", "has_gate": False},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    
    assert len(mission.workflow) == 1
    assert mission.workflow[0] == PriceScoutAgent


# =============================================================================
# Tests: _should_auto_proceed gate logic
# =============================================================================

def test_should_auto_proceed_no_config(mock_services, mission_state):
    """Test _should_auto_proceed defaults to False with no config."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    assert mission._should_auto_proceed(mission_state, 0) is False


def test_should_auto_proceed_gated_step(mock_services, mission_state):
    """Test _should_auto_proceed returns False for gated step."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True},
        {"agent_name": "SEOAgent", "has_gate": False},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    mission_state.workflow_config = config
    
    assert mission._should_auto_proceed(mission_state, 0) is False  # Gated


def test_should_auto_proceed_ungated_step(mock_services, mission_state):
    """Test _should_auto_proceed returns True for ungated step."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True},
        {"agent_name": "SEOAgent", "has_gate": False},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    mission_state.workflow_config = config
    
    assert mission._should_auto_proceed(mission_state, 1) is True  # Ungated


def test_should_auto_proceed_out_of_bounds(mock_services, mission_state):
    """Test _should_auto_proceed returns False for out-of-bounds index."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": False},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    mission_state.workflow_config = config
    
    assert mission._should_auto_proceed(mission_state, 5) is False


def test_should_auto_proceed_default_to_gated(mock_services, mission_state):
    """Test _should_auto_proceed defaults to gated when has_gate is missing."""
    config = [
        {"agent_name": "RewriterAgent"},  # Missing has_gate
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    mission_state.workflow_config = config
    
    # Default to gated for safety
    assert mission._should_auto_proceed(mission_state, 0) is False


# =============================================================================
# Tests: execute_single_step with workflow_config gate logic
# =============================================================================

@pytest.mark.asyncio
async def test_execute_single_step_gated_awaits_approval(mock_services, mission_state):
    """Test that gated step sets AWAITING_APPROVAL status."""
    async def mock_pass_through(self, state):
        state.draft_content = "Test"
        return state
    
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True},
        {"agent_name": "SEOAgent", "has_gate": True},
    ]
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )
        mission_state.workflow_config = config
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert final_state.status == "AWAITING_APPROVAL"
        assert final_state.current_agent_index == 0  # Not advanced


@pytest.mark.asyncio
async def test_execute_single_step_ungated_auto_proceeds(mock_services, mission_state):
    """Test that ungated step sets PENDING and advances index."""
    async def mock_pass_through(self, state):
        state.draft_content = "Test"
        return state
    
    config = [
        {"agent_name": "RewriterAgent", "has_gate": False},
        {"agent_name": "SEOAgent", "has_gate": True},
    ]
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )
        mission_state.workflow_config = config
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert final_state.status == "PENDING"
        assert final_state.current_agent_index == 1  # Auto-advanced


@pytest.mark.asyncio
async def test_execute_single_step_ungated_last_agent_completes(mock_services, mission_state):
    """Test that ungated last agent completes mission."""
    async def mock_pass_through(self, state):
        state.draft_content = "Test"
        return state
    
    config = [
        {"agent_name": "RewriterAgent", "has_gate": False},
    ]
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )
        mission_state.workflow_config = config
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert final_state.status == "COMPLETED"


@pytest.mark.asyncio
async def test_execute_single_step_no_config_defaults_gated(mock_services, mission_state):
    """Test that steps without workflow_config default to gated (AWAITING_APPROVAL)."""
    async def mock_pass_through(self, state):
        state.draft_content = "Test"
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
        assert final_state.status == "AWAITING_APPROVAL"


@pytest.mark.asyncio
async def test_execute_single_step_auto_proceed_logs(mock_services, mission_state):
    """Test that auto-proceeded steps log the gate status."""
    async def mock_pass_through(self, state):
        state.draft_content = "Test"
        return state
    
    config = [
        {"agent_name": "RewriterAgent", "has_gate": False},
        {"agent_name": "SEOAgent", "has_gate": True},
    ]
    
    with patch.object(CopywriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )
        mission_state.workflow_config = config
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        all_logs = "\n".join(states[-1].logs)
        assert "auto-approved" in all_logs.lower() or "no gate" in all_logs.lower()


@pytest.mark.asyncio
async def test_execute_single_step_stores_output_with_config(mock_services, mission_state):
    """Test that agent outputs are stored even with workflow_config."""
    async def mock_pass_through(self, state):
        state.draft_content = "Generated content"
        state.draft_title = "Generated title"
        return state
    
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True},
    ]
    
    with patch.object(RewriterAgent, 'run', mock_pass_through):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )
        mission_state.workflow_config = config
        
        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)
        
        final_state = states[-1]
        assert "RewriterAgent" in final_state.agent_outputs
        assert final_state.agent_outputs["RewriterAgent"]["draft_content"] == "Generated content"


# =============================================================================
# Tests: get_workflow_info with workflow_config
# =============================================================================

def test_get_workflow_info_with_workflow_config(mock_services):
    """Test get_workflow_info includes workflow_config info."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True},
        {"agent_name": "SEOAgent", "has_gate": False},
    ]
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )
    
    info = mission.get_workflow_info()
    
    assert info["agent_count"] == 2
    assert "RewriterAgent" in info["agents"]
    assert "SEOAgent" in info["agents"]


# =============================================================================
# Tests: Autonomous Execution Flag
# =============================================================================

def test_autonomous_flag_set_for_pro_tier(mock_services):
    """Test that autonomous flag is True for Pro tier."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    assert mission.autonomous is True


def test_autonomous_flag_false_for_standard_tier(mock_services):
    """Test that autonomous flag is False for Standard tier."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    assert mission.autonomous is False


def test_autonomous_flag_false_for_basic_tier(mock_services):
    """Test that autonomous flag is False for Basic tier."""
    mission = MissionControl(
        plan_tier="Basic",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    assert mission.autonomous is False


def test_autonomous_flag_false_for_free_tier(mock_services):
    """Test that autonomous flag is False for Free tier."""
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    assert mission.autonomous is False


# =============================================================================
# Tests: Autonomous flag propagation into state
# =============================================================================

@pytest.mark.asyncio
async def test_execute_propagates_autonomous_to_state(mock_services, mission_state):
    """Test that execute() sets state.autonomous from self.autonomous."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )

    states = []
    async for state in mission.execute(mission_state):
        states.append(state)

    # Every yielded state should have autonomous=True
    for s in states:
        assert s.autonomous is True, f"Expected autonomous=True, got {s.autonomous}"


@pytest.mark.asyncio
async def test_execute_single_step_propagates_autonomous(mock_services, mission_state):
    """Test that execute_single_step sets state.autonomous before running agent."""
    received_autonomous = [None]

    async def mock_capture_autonomous(self, state):
        received_autonomous[0] = state.autonomous
        state.draft_content = "ok"
        return state

    with patch.object(CopywriterAgent, 'run', mock_capture_autonomous):
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )

        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)

    assert received_autonomous[0] is True


@pytest.mark.asyncio
async def test_execute_single_step_non_pro_autonomous_false(mock_services, mission_state):
    """Test that non-Pro tier does NOT set state.autonomous."""
    received_autonomous = [None]

    async def mock_capture(self, state):
        received_autonomous[0] = state.autonomous
        return state

    with patch.object(CopywriterAgent, 'run', mock_capture):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )

        async for _ in mission.execute_single_step(mission_state):
            pass

    assert received_autonomous[0] is False


# =============================================================================
# Tests: _on_step_approved calls _maybe_publish
# =============================================================================

@pytest.mark.asyncio
async def test_on_step_approved_calls_maybe_publish_for_pro(mock_services, mission_state):
    """Test that _on_step_approved calls agent._maybe_publish when autonomous=True."""
    mission_state.autonomous = True
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True, "template_id": "product/description"},
    ]
    mission_state.workflow_config = config
    mission_state.agent_outputs["RewriterAgent:product/description"] = {"draft_content": "Test"}

    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )

    with patch.object(RewriterAgent, '_maybe_publish', new_callable=AsyncMock, return_value=(True, None)) as mock_pub:
        await mission._on_step_approved(mission_state, 0)
        mock_pub.assert_called_once()
        # Verify is_published was injected into agent_outputs
        assert mission_state.agent_outputs["RewriterAgent:product/description"]["is_published"] is True


@pytest.mark.asyncio
async def test_on_step_approved_skips_when_not_autonomous(mock_services, mission_state):
    """Test that _on_step_approved does nothing when autonomous=False."""
    mission_state.autonomous = False

    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )

    with patch.object(RewriterAgent, '_maybe_publish', new_callable=AsyncMock) as mock_pub:
        await mission._on_step_approved(mission_state, 0)
        mock_pub.assert_not_called()


@pytest.mark.asyncio
async def test_on_step_approved_records_publish_error(mock_services, mission_state):
    """Test that _on_step_approved records publish_error in agent_outputs."""
    mission_state.autonomous = True
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True, "template_id": "product/faq"},
    ]
    mission_state.workflow_config = config
    mission_state.agent_outputs["RewriterAgent:product/faq"] = {"draft_content": "FAQ data"}

    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )

    with patch.object(RewriterAgent, '_maybe_publish', new_callable=AsyncMock, return_value=(False, "missing_credentials")):
        await mission._on_step_approved(mission_state, 0)
        outputs = mission_state.agent_outputs["RewriterAgent:product/faq"]
        assert outputs["is_published"] is False
        assert outputs["publish_error"] == "missing_credentials"


# =============================================================================
# Tests: advance_to_next_step triggers _on_step_approved
# =============================================================================

@pytest.mark.asyncio
async def test_advance_to_next_step_triggers_on_step_approved(mock_services, mission_state):
    """Test that advance_to_next_step calls _on_step_approved before advancing."""
    on_step_calls = []

    async def mock_on_step(state, step_idx):
        on_step_calls.append(step_idx)

    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    mission._on_step_approved = mock_on_step

    mission_state.current_agent_index = 1
    result = await mission.advance_to_next_step(mission_state)

    assert on_step_calls == [1]
    assert result.current_agent_index == 2


# =============================================================================
# Tests: execute_single_step auto-proceed calls _on_step_approved
# =============================================================================

@pytest.mark.asyncio
async def test_auto_proceed_triggers_on_step_approved(mock_services, mission_state):
    """Test that auto-proceed path calls _on_step_approved."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": False},
        {"agent_name": "SEOAgent", "has_gate": True},
    ]
    mission_state.workflow_config = config

    async def mock_pass(self, state):
        state.draft_content = "content"
        return state

    on_step_calls = []

    async def capture_on_step(state, step_idx):
        on_step_calls.append(step_idx)

    with patch.object(CopywriterAgent, 'run', mock_pass):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )
        mission._on_step_approved = capture_on_step

        states = []
        async for state in mission.execute_single_step(mission_state):
            states.append(state)

    assert 0 in on_step_calls

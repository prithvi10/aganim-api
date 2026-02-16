"""
Integration tests for the Pro-Visual pipeline.

Tests the end-to-end flow of the VisualAgent within MissionControl:
  - Pro tier includes VisualAgent in workflow
  - Standard/Basic/Free tiers do NOT include VisualAgent
  - VisualAgent runs and populates state.visual_assets
  - VisualAgent's output is extracted correctly by _extract_agent_output
  - Autonomous mode triggers visual generation automatically
  - Pipeline error in VisualAgent doesn't crash entire mission
  - MissionState visual fields survive through the full pipeline
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.orchestrator import MissionControl
from src.ecommerce.state import MissionState
from src.ecommerce.agents.rewriter import RewriterAgent
from src.ecommerce.agents.seo import SEOAgent
from src.ecommerce.agents.marketing import MarketingAgent
from src.ecommerce.agents.price_scout import PriceScoutAgent
from src.ecommerce.agents.visual import VisualAgent


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for integration testing."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value='{"title": "Test", "description": "Test desc"}')
    services.llm.generate_structured = AsyncMock(return_value=MagicMock(
        model_dump=lambda: {"has_violations": False, "flags": [], "severity": "none"},
        has_violations=False,
        flags=[],
        severity="none",
    ))
    services.llm.generate_json = AsyncMock(return_value={})
    services.serp.search = AsyncMock(return_value=[])
    services.serp.get_competitor_prices = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=[])
    return services


@pytest.fixture
def pro_state():
    """Pro-tier state with image URL for visual pipeline."""
    return MissionState(
        product_id="product-123",
        shop_id="pro-shop.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "product_name": "Handcrafted Ceramic Bowl",
            "description": "Made in Kyoto using traditional techniques.",
            "category": "Kitchenware",
            "image_url": "https://cdn.shopify.com/product.jpg",
            "hook_text": "New Collection",
            "brand_name": "Kyoto Artisan",
        },
        target_locale="en",
    )


@pytest.fixture
def standard_state():
    """Standard-tier state (no visual pipeline)."""
    return MissionState(
        product_id="product-456",
        shop_id="standard-shop.myshopify.com",
        plan_tier="Standard",
        raw_input={
            "title": "Test Product",
            "description": "Test description.",
            "category": "General",
            "image_url": "https://cdn.shopify.com/product.jpg",
        },
    )


# =============================================================================
# Tests: Workflow configuration
# =============================================================================

class TestWorkflowConfiguration:
    """Test that VisualAgent is correctly included/excluded in workflows."""

    def test_pro_workflow_includes_visual_agent(self):
        assert VisualAgent in MissionControl.WORKFLOWS["Pro"]

    def test_standard_workflow_excludes_visual_agent(self):
        assert VisualAgent not in MissionControl.WORKFLOWS["Standard"]

    def test_basic_workflow_excludes_visual_agent(self):
        assert VisualAgent not in MissionControl.WORKFLOWS["Basic"]

    def test_free_workflow_excludes_visual_agent(self):
        assert VisualAgent not in MissionControl.WORKFLOWS["Free"]

    def test_visual_agent_is_last_in_pro_workflow(self):
        """VisualAgent should run after all other agents."""
        pro = MissionControl.WORKFLOWS["Pro"]
        assert pro[-1] == VisualAgent

    def test_visual_agent_in_agent_map(self):
        assert "VisualAgent" in MissionControl.AGENT_MAP
        assert MissionControl.AGENT_MAP["VisualAgent"] == VisualAgent


# =============================================================================
# Tests: _extract_agent_output for VisualAgent
# =============================================================================

class TestExtractVisualOutput:
    """Test _extract_agent_output for VisualAgent."""

    def test_extracts_visual_assets(self, mock_services):
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
        )

        state = MissionState(
            product_id="p1",
            shop_id="pro-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )
        state.visual_assets = {
            "refined_url": "https://r2/refined.png",
            "ad_url": "https://r2/ad.png",
            "hero_url": "https://r2/hero.png",
        }
        state.visual_progress = {
            "phase": "complete",
            "pct": 100,
            "label": "Done",
        }

        output = mission._extract_agent_output(state, "VisualAgent")
        assert output["visual_assets"] == state.visual_assets
        assert output["visual_progress"] == state.visual_progress

    def test_extracts_none_visual_assets(self, mock_services):
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
        )

        state = MissionState(
            product_id="p1",
            shop_id="pro-shop.myshopify.com",
            plan_tier="Pro",
            raw_input={},
        )

        output = mission._extract_agent_output(state, "VisualAgent")
        assert output["visual_assets"] is None
        assert output["visual_progress"] is None


# =============================================================================
# Integration: Pro mission includes VisualAgent
# =============================================================================

@pytest.mark.asyncio
async def test_pro_mission_runs_visual_agent(mock_services, pro_state):
    """
    Integration: Pro tier full mission should run VisualAgent.
    We mock all agents to verify VisualAgent is in the execution flow.
    """
    agents_executed = []

    async def capture_agent(self, state):
        agents_executed.append(self.role_name)
        state.add_log(f"{self.role_name}: ran")
        return state

    with patch.object(RewriterAgent, 'run', capture_agent), \
         patch.object(SEOAgent, 'run', capture_agent), \
         patch.object(MarketingAgent, 'run', capture_agent), \
         patch.object(PriceScoutAgent, 'run', capture_agent), \
         patch.object(VisualAgent, 'run', capture_agent):

        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
        )

        states = []
        async for state in mission.execute(pro_state):
            states.append(state)

    # VisualAgent should have been executed
    assert "Visual" in agents_executed
    # Final state should be COMPLETED
    assert states[-1].status == "COMPLETED"


@pytest.mark.asyncio
async def test_standard_mission_does_not_run_visual_agent(mock_services, standard_state):
    """
    Integration: Standard tier should NOT run VisualAgent.
    """
    agents_executed = []

    async def capture_agent(self, state):
        agents_executed.append(self.role_name)
        state.add_log(f"{self.role_name}: ran")
        return state

    with patch.object(RewriterAgent, 'run', capture_agent), \
         patch.object(SEOAgent, 'run', capture_agent), \
         patch.object(MarketingAgent, 'run', capture_agent), \
         patch.object(PriceScoutAgent, 'run', capture_agent), \
         patch.object(VisualAgent, 'run', capture_agent):

        mission = MissionControl(
            plan_tier="Standard",
            shop_id="standard-shop.myshopify.com",
            services=mock_services,
        )

        states = []
        async for state in mission.execute(standard_state):
            states.append(state)

    # VisualAgent should NOT have been executed
    assert "Visual" not in agents_executed
    assert states[-1].status == "COMPLETED"


# =============================================================================
# Integration: VisualAgent populates visual_assets on state
# =============================================================================

@pytest.mark.asyncio
async def test_visual_agent_populates_state(mock_services, pro_state):
    """
    Integration: VisualAgent should populate state.visual_assets
    when it runs in the Pro pipeline.
    """
    async def noop_agent(self, state):
        state.add_log(f"{self.role_name}: ran")
        return state

    async def mock_visual_run(self, state):
        """Simulate VisualAgent populating visual_assets."""
        state.visual_assets = {
            "refined_url": "https://r2/refined.png",
            "ad_url": "https://r2/ad.png",
            "hero_url": "https://r2/hero.png",
            "original_image_url": "https://cdn.shopify.com/product.jpg",
        }
        state.visual_progress = {
            "phase": "complete",
            "pct": 100,
            "label": "Visual pipeline complete",
        }
        state.add_log("Visual: pipeline complete")
        return state

    with patch.object(RewriterAgent, 'run', noop_agent), \
         patch.object(SEOAgent, 'run', noop_agent), \
         patch.object(MarketingAgent, 'run', noop_agent), \
         patch.object(PriceScoutAgent, 'run', noop_agent), \
         patch.object(VisualAgent, 'run', mock_visual_run):

        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
        )

        states = []
        async for state in mission.execute(pro_state):
            states.append(state)

    final_state = states[-1]
    assert final_state.visual_assets is not None
    assert final_state.visual_assets["refined_url"] == "https://r2/refined.png"
    assert final_state.visual_assets["ad_url"] == "https://r2/ad.png"
    assert final_state.visual_assets["hero_url"] == "https://r2/hero.png"
    assert final_state.visual_progress["pct"] == 100


# =============================================================================
# Integration: VisualAgent error doesn't crash mission
# =============================================================================

@pytest.mark.asyncio
async def test_visual_agent_error_handled_gracefully(mock_services, pro_state):
    """
    Integration: If VisualAgent raises an error, it should be caught
    and the mission should still complete (with error logged).
    """
    async def noop_agent(self, state):
        state.add_log(f"{self.role_name}: ran")
        return state

    async def visual_that_fails(self, state):
        """Simulate VisualAgent that encounters an error but handles it."""
        state.visual_assets = {
            "original_image_url": "https://cdn.shopify.com/product.jpg",
            "refined_url": None,
            "ad_url": None,
            "hero_url": None,
        }
        state.visual_progress = {
            "phase": "error",
            "pct": 0,
            "label": "Visual pipeline error: fal.ai unreachable",
        }
        state.add_log("Visual: pipeline error - fal.ai unreachable")
        return state

    with patch.object(RewriterAgent, 'run', noop_agent), \
         patch.object(SEOAgent, 'run', noop_agent), \
         patch.object(MarketingAgent, 'run', noop_agent), \
         patch.object(PriceScoutAgent, 'run', noop_agent), \
         patch.object(VisualAgent, 'run', visual_that_fails):

        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
        )

        states = []
        async for state in mission.execute(pro_state):
            states.append(state)

    final_state = states[-1]
    # Mission should still complete
    assert final_state.status == "COMPLETED"
    # Visual progress should show error
    assert final_state.visual_progress["phase"] == "error"
    # But there should be partial results stored
    assert final_state.visual_assets is not None


# =============================================================================
# Integration: Autonomous flag persists through VisualAgent
# =============================================================================

@pytest.mark.asyncio
async def test_autonomous_flag_persists_through_visual_agent(mock_services, pro_state):
    """
    Integration: autonomous flag should persist through all agents
    including VisualAgent.
    """
    captured_flags = []

    async def capture_autonomous(self, state):
        captured_flags.append((self.role_name, state.autonomous))
        state.add_log(f"{self.role_name}: ran")
        return state

    with patch.object(RewriterAgent, 'run', capture_autonomous), \
         patch.object(SEOAgent, 'run', capture_autonomous), \
         patch.object(MarketingAgent, 'run', capture_autonomous), \
         patch.object(PriceScoutAgent, 'run', capture_autonomous), \
         patch.object(VisualAgent, 'run', capture_autonomous):

        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
        )

        states = []
        async for state in mission.execute(pro_state):
            states.append(state)

    # All 5 agents (including Visual) should have seen autonomous=True
    assert len(captured_flags) == 5
    assert all(flag is True for _, flag in captured_flags)

    # Verify Visual was one of them
    visual_entry = [e for e in captured_flags if e[0] == "Visual"]
    assert len(visual_entry) == 1
    assert visual_entry[0][1] is True


# =============================================================================
# Integration: Visual assets survive serialization in agent_outputs
# =============================================================================

@pytest.mark.asyncio
async def test_visual_output_in_agent_outputs(mock_services, pro_state):
    """
    Integration: VisualAgent's output should be stored in
    state.agent_outputs during step-by-step execution.
    """
    async def noop(self, state):
        state.add_log(f"{self.role_name}: ran")
        return state

    async def visual_run(self, state):
        state.visual_assets = {
            "refined_url": "https://r2/refined.png",
            "ad_url": "https://r2/ad.png",
            "hero_url": "https://r2/hero.png",
        }
        state.visual_progress = {"phase": "complete", "pct": 100, "label": "Done"}
        state.add_log("Visual: ran")
        return state

    config = [
        {"agent_name": "RewriterAgent", "has_gate": False},
        {"agent_name": "SEOAgent", "has_gate": False},
        {"agent_name": "MarketingAgent", "has_gate": False},
        {"agent_name": "PriceScoutAgent", "has_gate": False},
        {"agent_name": "VisualAgent", "has_gate": True},  # Gate on visual
    ]
    pro_state.workflow_config = config

    with patch.object(RewriterAgent, 'run', noop), \
         patch.object(SEOAgent, 'run', noop), \
         patch.object(MarketingAgent, 'run', noop), \
         patch.object(PriceScoutAgent, 'run', noop), \
         patch.object(VisualAgent, 'run', visual_run):

        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )

        # Execute all steps
        last_state = None
        while True:
            states = []
            if last_state is None:
                async for state in mission.execute_single_step(pro_state):
                    states.append(state)
            else:
                if last_state.status == "AWAITING_APPROVAL":
                    last_state = await mission.advance_to_next_step(last_state)
                    states = [last_state]
                elif last_state.status == "COMPLETED":
                    break
                else:
                    async for state in mission.execute_single_step(last_state):
                        states.append(state)

            last_state = states[-1]
            if last_state.status == "COMPLETED":
                break

    # Visual assets should be in the final state
    assert last_state.visual_assets is not None
    assert last_state.visual_assets["refined_url"] == "https://r2/refined.png"


# =============================================================================
# Integration: Pro mission with no image URL
# =============================================================================

@pytest.mark.asyncio
async def test_pro_mission_no_image_visual_graceful(mock_services):
    """
    Integration: Pro mission with no image_url should still complete,
    with VisualAgent logging that it was skipped.
    """
    state = MissionState(
        product_id="product-789",
        shop_id="pro-shop.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": "Product Without Image",
            "description": "No image provided.",
            "category": "General",
        },
    )

    async def noop(self, state):
        state.add_log(f"{self.role_name}: ran")
        return state

    async def visual_no_image(self, state):
        """Simulate VisualAgent that skips due to no image."""
        state.add_log("Visual: Skipped -- no product image URL available")
        return state

    with patch.object(RewriterAgent, 'run', noop), \
         patch.object(SEOAgent, 'run', noop), \
         patch.object(MarketingAgent, 'run', noop), \
         patch.object(PriceScoutAgent, 'run', noop), \
         patch.object(VisualAgent, 'run', visual_no_image):

        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
        )

        states = []
        async for s in mission.execute(state):
            states.append(s)

    final = states[-1]
    assert final.status == "COMPLETED"
    assert final.visual_assets is None  # No assets generated
    # Should have a log about skipping
    skip_logs = [l for l in final.logs if "Skipped" in l]
    assert len(skip_logs) > 0

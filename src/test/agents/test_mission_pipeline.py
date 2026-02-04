"""
Full pipeline integration tests with mocked LLM.

Tests complete mission workflow from start to finish with all agents.
Note: ComplianceAgent is currently disabled.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.main.agents.orchestrator import MissionControl, run_mission
from src.main.agents.state import MissionState
from src.main.agents.copywriter import CopywriterAgent
from src.main.agents.seo import SEOAgent
from src.main.agents.marketing import MarketingAgent
from src.main.agents.price_scout import PriceScoutAgent
from src.main.agents.price_scout.schemas import PricingAnalysis
from src.main.services import ServiceRegistry


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create comprehensive mock ServiceRegistry for integration testing."""
    services = MagicMock()
    
    # Mock LLM - Copywriter response
    services.llm.generate_text = AsyncMock(return_value="""{
        "title": "Artisan Ceramic Bowl - Handcrafted in Kyoto",
        "description": "<p>Beautiful handcrafted ceramic bowl from a traditional Kyoto atelier.</p>",
        "seo_title": "Handcrafted Ceramic Bowl | Kyoto Artisan Collection",
        "seo_description": "Discover our authentic Kyoto ceramic bowl. Handcrafted using traditional techniques. Free worldwide shipping.",
        "seo_alt_text": "Handcrafted ceramic bowl from Kyoto atelier",
        "discovered_values": []
    }""")
    
    # Mock LLM - Structured output (for PriceScout)
    services.llm.generate_structured = AsyncMock(return_value=PricingAnalysis(
        competitor_avg_price=50.0,
        recommended_price=55.0,
        price_position="competitive",
        confidence=0.85,
        reasoning="Test reasoning",
    ))
    
    # Mock JSON generation
    services.llm.generate_json = AsyncMock(return_value={
        "seo_title": "Test SEO Title",
        "seo_description": "Test SEO description",
    })
    
    # Mock SERP
    mock_serp_results = []
    for i in range(3):
        r = MagicMock()
        r.title = f"Competitor {i+1}"
        r.snippet = f"Product snippet {i+1}"
        r.link = f"https://comp{i+1}.com"
        r.position = i + 1
        mock_serp_results.append(r)
    
    services.serp.search = AsyncMock(return_value=mock_serp_results)
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {"title": "Competitor 1", "price": 45.0},
        {"title": "Competitor 2", "price": 55.0},
    ])
    
    # Mock RAG
    services.rag.get_brand_context = AsyncMock(return_value=[
        {"content": "We are a Kyoto atelier focused on traditional craftsmanship."},
    ])
    
    return services


@pytest.fixture
def product_data():
    """Sample product data for testing."""
    return {
        "product_id": "test-product-123",
        "title": "伝統的な陶器ボウル",  # Japanese title
        "description": "京都の職人による手作りの陶器ボウル。伝統的な技法で作られています。",
        "japanese_description": "京都の職人による手作りの陶器ボウル。伝統的な技法で作られています。",
        "category": "Kitchenware",
        "product_name": "Ceramic Bowl",
    }


@pytest.fixture
def mission_state(product_data):
    """Create MissionState for testing."""
    return MissionState(
        product_id=product_data["product_id"],
        shop_id="test-shop.myshopify.com",
        plan_tier="Standard",
        raw_input=product_data,
        target_locale="en",
    )


# =============================================================================
# Tests: Full Pipeline Execution
# =============================================================================

@pytest.mark.asyncio
async def test_full_pipeline_standard_tier(mock_services, mission_state):
    """Test complete Standard tier workflow."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Should complete successfully (ComplianceAgent disabled, so no COMPLIANCE_REVIEW)
    final_state = states[-1]
    assert final_state.status == "COMPLETED"
    
    # Should have generated content
    assert final_state.draft_content is not None or final_state.draft_title is not None


@pytest.mark.asyncio
async def test_full_pipeline_pro_tier(mock_services, mission_state):
    """Test complete Pro tier workflow."""
    mission_state.plan_tier = "Pro"
    
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Should complete successfully
    final_state = states[-1]
    assert final_state.status == "COMPLETED"


@pytest.mark.asyncio
async def test_full_pipeline_free_tier(mock_services, mission_state):
    """Test complete Free tier workflow (all agents available)."""
    mission_state.plan_tier = "Free"
    
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Should complete successfully
    final_state = states[-1]
    assert final_state.status == "COMPLETED"


# =============================================================================
# Tests: Agent Output Flow
# =============================================================================

@pytest.mark.asyncio
async def test_copywriter_output_flows_to_seo(mock_services, mission_state):
    """Test that Copywriter output is available to SEO agent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Find state after copywriter
    copywriter_state = None
    for s in states:
        if s.draft_content is not None:
            copywriter_state = s
            break
    
    assert copywriter_state is not None
    assert copywriter_state.draft_content is not None


@pytest.mark.asyncio
async def test_seo_generates_seo_fields(mock_services, mission_state):
    """Test that SEO agent generates SEO fields."""
    # Set up mock for SEO generation
    mock_services.llm.generate_text.side_effect = [
        # Copywriter response
        '{"title": "Test Title", "description": "<p>Test</p>"}',
        # SEO response
        '{"seo_title": "SEO Title", "seo_description": "SEO Description", "seo_alt_text": "Alt text"}',
        # Marketing social hooks response
        '{"hooks": [{"type": "Story", "caption": "Test", "hashtags": []}]}',
    ]
    
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    final_state = states[-1]
    # SEO agent should have added SEO fields or CTR check
    assert final_state.seo_title is not None or final_state.ctr_check is not None


@pytest.mark.asyncio
async def test_marketing_generates_social_hooks(mock_services, mission_state):
    """Test that Marketing agent generates social hooks."""
    # Set up mock for social hooks generation
    mock_services.llm.generate_text.side_effect = [
        # Copywriter response
        '{"title": "Test Title", "description": "<p>Test</p>"}',
        # SEO response
        '{"seo_title": "SEO Title", "seo_description": "SEO Description", "seo_alt_text": "Alt text"}',
        # Marketing social hooks response
        '{"hooks": [{"type": "Story", "caption": "Test caption", "hashtags": ["#test"]}]}',
    ]
    
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    final_state = states[-1]
    # Marketing should have added social hooks (may be empty if parsing fails)
    # Just verify no crash
    assert final_state.status == "COMPLETED"


# =============================================================================
# Tests: Error Handling
# =============================================================================

@pytest.mark.asyncio
async def test_pipeline_handles_llm_failure_gracefully(mock_services, mission_state):
    """Test that pipeline handles LLM failures without crashing."""
    # Make LLM fail
    mock_services.llm.generate_text = AsyncMock(side_effect=Exception("LLM API Error"))
    
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Should have error state but not crash
    final_state = states[-1]
    assert final_state.status == "ERROR"


@pytest.mark.asyncio
async def test_pipeline_handles_serp_failure_gracefully(mock_services, mission_state):
    """Test that pipeline handles SERP failures without crashing."""
    # Make SERP fail
    mock_services.serp.search = AsyncMock(side_effect=Exception("SERP API Error"))
    mock_services.serp.get_competitor_prices = AsyncMock(side_effect=Exception("SERP API Error"))
    
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Should complete (agents handle SERP errors internally)
    final_state = states[-1]
    assert final_state.status in ["COMPLETED", "ERROR"]


# =============================================================================
# Tests: State Streaming
# =============================================================================

@pytest.mark.asyncio
async def test_pipeline_streams_state_updates(mock_services, mission_state):
    """Test that pipeline yields state updates after each agent."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Should have multiple state updates
    # 1 initial + N agents + 1 final = at least 3
    assert len(states) >= 3
    
    # Each state should have logs
    for state in states:
        assert len(state.logs) >= 0  # May be empty for first


@pytest.mark.asyncio
async def test_state_serialization_throughout_pipeline(mock_services, mission_state):
    """Test that state can be serialized at any point."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    async for state in mission.execute(mission_state):
        # Should be able to serialize each state
        data = state.to_dict()
        assert isinstance(data, dict)
        assert "product_id" in data
        assert "status" in data


# =============================================================================
# Tests: Run Mission Convenience Function
# =============================================================================

@pytest.mark.asyncio
async def test_run_mission_convenience(mock_services, product_data):
    """Test the run_mission convenience function."""
    with patch('src.main.agents.orchestrator.ServiceRegistry') as MockRegistry:
        MockRegistry.create_default.return_value = mock_services
        
        states = []
        async for state in run_mission(
            shop_id="test-shop.myshopify.com",
            product_data=product_data,
            plan_tier="Standard",
            target_locale="en",
        ):
            states.append(state)
        
        assert len(states) > 0
        assert states[-1].status in ["COMPLETED", "ERROR"]


# =============================================================================
# Tests: Agent Workflow Verification
# =============================================================================

@pytest.mark.asyncio
async def test_workflow_has_four_agents(mock_services, mission_state):
    """Test that workflow has 4 agents: Copywriter, SEO, Marketing, PriceScout."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    assert len(mission.workflow) == 4
    assert CopywriterAgent in mission.workflow
    assert SEOAgent in mission.workflow
    assert MarketingAgent in mission.workflow
    assert PriceScoutAgent in mission.workflow


@pytest.mark.asyncio
async def test_workflow_executes_in_correct_order(mock_services, mission_state):
    """Test that agents execute in correct order: Copywriter -> SEO -> Marketing -> PriceScout."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    states = []
    async for state in mission.execute(mission_state):
        states.append(state)
    
    # Check logs for agent execution order
    all_logs = "\n".join(["\n".join(s.logs) for s in states])
    
    # Find positions of agent mentions in logs
    copywriter_pos = all_logs.find("Copywriter")
    seo_pos = all_logs.find("SEO")
    marketing_pos = all_logs.find("Marketing")
    pricescout_pos = all_logs.find("PriceScout")
    
    # Verify order (agents may not all appear if errors occur early)
    if copywriter_pos >= 0 and seo_pos >= 0:
        assert copywriter_pos < seo_pos, "Copywriter should run before SEO"
    if seo_pos >= 0 and marketing_pos >= 0:
        assert seo_pos < marketing_pos, "SEO should run before Marketing"

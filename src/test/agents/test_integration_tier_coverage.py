"""
Integration tests for tier-based agent coverage.

Confirms that all agents run for each subscription tier.
Tier→Agent mapping (plan gating overhaul):
  Free: 6 (full pipeline incl. image agents — taste of Pro)
  Basic: 2 (Rewriter + Marketing only)
  Standard: 4 (Rewriter, SEO, Marketing, PriceScout — no image agents)
  Pro: 6 (all agents)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.ecommerce.orchestrator import MissionControl
from src.ecommerce.state import MissionState
from src.ecommerce.agents.rewriter import RewriterAgent
CopywriterAgent = RewriterAgent  # Backward compat alias
from src.ecommerce.agents.seo import SEOAgent
from src.ecommerce.agents.marketing import MarketingAgent
from src.ecommerce.agents.price_scout import PriceScoutAgent
from src.ecommerce.agents.price_scout.schemas import PricingAnalysis


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create comprehensive mock ServiceRegistry."""
    services = MagicMock()
    
    # Mock LLM - Copywriter response
    services.llm.generate_text = AsyncMock(return_value="""{
        "title": "Test Title",
        "description": "<p>Test description</p>",
        "seo_title": "SEO Title",
        "seo_description": "SEO Description",
        "seo_alt_text": "Alt text",
        "discovered_values": []
    }""")
    
    # Mock LLM - Structured output (type-aware)
    async def mock_structured(*args, **kwargs):
        response_format = kwargs.get('response_format')
        if response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=50.0,
                recommended_price=55.0,
                price_position="competitive",
                confidence=0.85,
                reasoning="Test reasoning",
            )
        return MagicMock()
    
    services.llm.generate_structured = AsyncMock(side_effect=mock_structured)
    services.llm.generate_json = AsyncMock(return_value={})
    
    # Mock SERP
    mock_serp_results = []
    for i in range(3):
        r = MagicMock()
        r.title = f"Competitor {i+1}"
        r.snippet = f"Snippet {i+1}"
        r.link = f"https://comp{i+1}.com"
        r.position = i + 1
        mock_serp_results.append(r)
    
    services.serp.search = AsyncMock(return_value=mock_serp_results)
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {"title": "Competitor 1", "price": 45.0},
        {"title": "Competitor 2", "price": 55.0},
    ])
    
    # Mock RAG
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def product_data():
    """Sample product data."""
    return {
        "product_id": "test-123",
        "title": "Test Product",
        "description": "Test description",
        "category": "Kitchenware",
    }


def create_mission_state(product_data, plan_tier):
    """Create MissionState for a specific tier."""
    return MissionState(
        product_id=product_data["product_id"],
        shop_id="test-shop.myshopify.com",
        plan_tier=plan_tier,
        raw_input=product_data,
        target_locale="en",
    )


# =============================================================================
# Tests: Free Tier Agent Coverage
# =============================================================================

@pytest.mark.asyncio
async def test_free_tier_runs_all_agents(mock_services, product_data):
    """Test that FREE tier runs all 6 agents (full Pro pipeline, taste of Pro)."""
    state = create_mission_state(product_data, "Free")
    
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    all_logs = []
    async for s in mission.execute(state):
        all_logs.extend(s.logs)
    
    logs_text = "\n".join(all_logs)
    
    assert "Running Rewriter" in logs_text, "Rewriter should run for Free tier"
    assert "Running SEO" in logs_text, "SEO should run for Free tier"
    assert "Running Marketing" in logs_text, "Marketing should run for Free tier"
    assert "Running PriceScout" in logs_text, "PriceScout should run for Free tier"


@pytest.mark.asyncio
async def test_free_tier_workflow_contains_all_agents(mock_services):
    """Test that FREE tier workflow includes all 6 agents (incl. image agents)."""
    mission = MissionControl(
        plan_tier="Free",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    assert CopywriterAgent in mission.workflow
    assert SEOAgent in mission.workflow
    assert MarketingAgent in mission.workflow
    assert PriceScoutAgent in mission.workflow
    assert len(mission.workflow) == 6


# =============================================================================
# Tests: Basic Tier Agent Coverage
# =============================================================================

@pytest.mark.asyncio
async def test_basic_tier_runs_all_agents(mock_services, product_data):
    """Test that BASIC tier runs 2 agents (Rewriter + Marketing)."""
    state = create_mission_state(product_data, "Basic")
    
    mission = MissionControl(
        plan_tier="Basic",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    all_logs = []
    async for s in mission.execute(state):
        all_logs.extend(s.logs)
    
    logs_text = "\n".join(all_logs)
    
    assert "Running Rewriter" in logs_text
    assert "Running Marketing" in logs_text


@pytest.mark.asyncio
async def test_basic_tier_workflow_contains_all_agents(mock_services):
    """Test that BASIC tier workflow has Rewriter + Marketing (2 agents)."""
    mission = MissionControl(
        plan_tier="Basic",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    assert len(mission.workflow) == 2
    assert CopywriterAgent in mission.workflow
    assert MarketingAgent in mission.workflow


# =============================================================================
# Tests: Standard Tier Agent Coverage
# =============================================================================

@pytest.mark.asyncio
async def test_standard_tier_runs_all_agents(mock_services, product_data):
    """Test that STANDARD tier runs all 4 agents."""
    state = create_mission_state(product_data, "Standard")
    
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    all_logs = []
    async for s in mission.execute(state):
        all_logs.extend(s.logs)
    
    logs_text = "\n".join(all_logs)
    
    assert "Running Rewriter" in logs_text
    assert "Running SEO" in logs_text
    assert "Running Marketing" in logs_text
    assert "Running PriceScout" in logs_text


@pytest.mark.asyncio
async def test_standard_tier_workflow_contains_all_agents(mock_services):
    """Test that STANDARD tier workflow configuration includes all agents."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    assert len(mission.workflow) == 4


# =============================================================================
# Tests: Pro Tier Agent Coverage
# =============================================================================

@pytest.mark.asyncio
async def test_pro_tier_runs_all_agents(mock_services, product_data):
    """Test that PRO tier runs all 4 agents."""
    state = create_mission_state(product_data, "Pro")
    
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    all_logs = []
    async for s in mission.execute(state):
        all_logs.extend(s.logs)
    
    logs_text = "\n".join(all_logs)
    
    assert "Running Rewriter" in logs_text
    assert "Running SEO" in logs_text
    assert "Running Marketing" in logs_text
    assert "Running PriceScout" in logs_text


@pytest.mark.asyncio
async def test_pro_tier_workflow_contains_all_agents(mock_services):
    """Test that PRO tier workflow configuration includes all agents (incl. VisualAgent)."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="test-shop.myshopify.com",
        services=mock_services,
    )
    
    assert len(mission.workflow) == 6


# =============================================================================
# Tests: Cross-Tier Comparison
# =============================================================================

@pytest.mark.asyncio
async def test_all_tiers_have_expected_agent_count(mock_services):
    """Test that all tiers have the expected number of agents."""
    expected = {"Free": 6, "Basic": 2, "Standard": 4, "Pro": 6}
    
    for tier, count in expected.items():
        mission = MissionControl(
            plan_tier=tier,
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        assert len(mission.workflow) == count, f"{tier} tier should have {count} agents"


@pytest.mark.asyncio
async def test_all_tiers_complete_successfully(mock_services, product_data):
    """Test that all tiers complete successfully."""
    tiers = ["Free", "Basic", "Standard", "Pro"]
    
    for tier in tiers:
        state = create_mission_state(product_data, tier)
        
        mission = MissionControl(
            plan_tier=tier,
            shop_id="test-shop.myshopify.com",
            services=mock_services,
        )
        
        final_state = None
        async for s in mission.execute(state):
            final_state = s
        
        assert final_state.status == "COMPLETED", \
            f"{tier} tier should complete successfully"

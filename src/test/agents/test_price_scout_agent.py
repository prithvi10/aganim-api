"""
Unit tests for PriceScoutAgent.

Tests SERP competitor fetching, structured LLM analysis, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.main.agents.price_scout import PriceScoutAgent
from src.main.agents.price_scout.schemas import PricingAnalysis
from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for testing."""
    services = MagicMock()
    
    # Mock SERP service
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {"title": "Competitor 1", "snippet": "Premium ceramic bowl $45", "price": 45.0},
        {"title": "Competitor 2", "snippet": "Artisan bowl $55", "price": 55.0},
        {"title": "Competitor 3", "snippet": "Handmade bowl $40", "price": 40.0},
    ])
    
    # Mock LLM service - structured output
    services.llm.generate_structured = AsyncMock(return_value=PricingAnalysis(
        competitor_avg_price=46.67,
        recommended_price=50.0,
        price_position="competitive",
        confidence=0.85,
        reasoning="Based on competitor analysis, pricing at $50 positions the product competitively.",
    ))
    
    services.rag.get_brand_context = AsyncMock(return_value=[])
    services.llm.generate_text = AsyncMock(return_value="{}")
    
    return services


@pytest.fixture
def mission_state():
    """Create a basic MissionState for testing."""
    return MissionState(
        product_id="test-product-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "description": "Made in Kyoto using traditional techniques.",
            "category": "Kitchenware",
        },
        target_locale="en",
    )


# =============================================================================
# Tests: Perception Phase (SERP Competitor Fetching)
# =============================================================================

@pytest.mark.asyncio
async def test_perceive_fetches_competitors(mock_services, mission_state):
    """Test that perception fetches competitor data via SERP."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    context = await agent.perceive(mission_state)
    
    # Should have called SERP service
    mock_services.serp.get_competitor_prices.assert_called_once()
    
    # Should have competitor data in context
    assert "competitors" in context.external_data
    assert len(context.external_data["competitors"]) == 3
    assert context.external_data["competitor_count"] == 3


@pytest.mark.asyncio
async def test_perceive_handles_empty_competitors(mock_services, mission_state):
    """Test that perception handles no competitor data."""
    mock_services.serp.get_competitor_prices = AsyncMock(return_value=[])
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should have empty competitors
    assert context.external_data["competitors"] == []
    assert context.external_data["competitor_count"] == 0


@pytest.mark.asyncio
async def test_perceive_handles_serp_error(mock_services, mission_state):
    """Test that perception handles SERP errors gracefully."""
    mock_services.serp.get_competitor_prices = AsyncMock(side_effect=Exception("SERP error"))
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should have empty competitors on error
    assert context.external_data["competitors"] == []
    assert context.external_data["competitor_count"] == 0


# =============================================================================
# Tests: Action Phase (Structured LLM Analysis)
# =============================================================================

@pytest.mark.asyncio
async def test_act_generates_pricing_analysis(mock_services, mission_state):
    """Test that action generates pricing analysis."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should have pricing analysis
    assert result.pricing_analysis is not None
    assert "competitor_avg_price" in result.pricing_analysis
    assert "recommended_price" in result.pricing_analysis


@pytest.mark.asyncio
async def test_act_uses_structured_output(mock_services, mission_state):
    """Test that action uses generate_structured method."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state)
    
    # Should have called generate_structured
    mock_services.llm.generate_structured.assert_called_once()
    
    # Check that it was called with PricingAnalysis schema
    call_args = mock_services.llm.generate_structured.call_args
    assert call_args.kwargs["response_format"] == PricingAnalysis


@pytest.mark.asyncio
async def test_act_uses_gpt4o_mini(mock_services, mission_state):
    """Test that action uses cheaper gpt-4o-mini model."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state)
    
    call_args = mock_services.llm.generate_structured.call_args
    assert call_args.kwargs.get("model") == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_act_skips_llm_without_competitors(mock_services, mission_state):
    """Test that action skips LLM call when no competitors."""
    mock_services.serp.get_competitor_prices = AsyncMock(return_value=[])
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should NOT have called LLM
    mock_services.llm.generate_structured.assert_not_called()
    
    # Should still have pricing analysis (empty)
    assert result.pricing_analysis is not None
    assert result.pricing_analysis["competitor_count"] == 0
    assert result.pricing_analysis["confidence"] == 0.0


# =============================================================================
# Tests: Structured Output Parsing
# =============================================================================

@pytest.mark.asyncio
async def test_pricing_analysis_structure(mock_services, mission_state):
    """Test that pricing analysis has expected structure."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    analysis = result.pricing_analysis
    
    # Check all expected fields
    assert "competitor_avg_price" in analysis
    assert "recommended_price" in analysis
    assert "price_position" in analysis
    assert "confidence" in analysis
    assert "reasoning" in analysis
    assert "competitor_count" in analysis


@pytest.mark.asyncio
async def test_pricing_analysis_confidence_range(mock_services, mission_state):
    """Test that confidence is in valid range."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    confidence = result.pricing_analysis["confidence"]
    assert 0.0 <= confidence <= 1.0


# =============================================================================
# Tests: Error Handling
# =============================================================================

@pytest.mark.asyncio
async def test_handles_llm_error(mock_services, mission_state):
    """Test that agent handles LLM errors gracefully."""
    mock_services.llm.generate_structured = AsyncMock(side_effect=Exception("LLM error"))
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should complete but have None analysis
    assert result.pricing_analysis is None


# =============================================================================
# Tests: Prompt Building
# =============================================================================

def test_build_analysis_prompt():
    """Test that analysis prompt is built correctly."""
    agent = PriceScoutAgent("test-shop", MagicMock())
    
    competitors = [
        {"title": "Product A", "snippet": "Snippet A"},
        {"title": "Product B", "snippet": "Snippet B"},
    ]
    
    prompt = agent._build_analysis_prompt(
        product_name="Test Product",
        category="Kitchenware",
        competitors=competitors,
    )
    
    assert "Test Product" in prompt
    assert "Kitchenware" in prompt
    assert "Product A" in prompt
    assert "Product B" in prompt


def test_build_analysis_prompt_limits_competitors():
    """Test that prompt limits to 5 competitors."""
    agent = PriceScoutAgent("test-shop", MagicMock())
    
    # Create 10 competitors
    competitors = [
        {"title": f"Product {i}", "snippet": f"Snippet {i}"}
        for i in range(10)
    ]
    
    prompt = agent._build_analysis_prompt(
        product_name="Test Product",
        category="Category",
        competitors=competitors,
    )
    
    # Should only include first 5
    assert "Product 0" in prompt
    assert "Product 4" in prompt
    # Product 5 and above should not be included
    assert "Product 5" not in prompt


# =============================================================================
# Tests: Schema Validation
# =============================================================================

def test_pricing_analysis_schema():
    """Test PricingAnalysis Pydantic schema."""
    analysis = PricingAnalysis(
        competitor_avg_price=50.0,
        recommended_price=55.0,
        price_position="premium",
        confidence=0.9,
        reasoning="Test reasoning",
    )
    
    assert analysis.competitor_avg_price == 50.0
    assert analysis.recommended_price == 55.0
    assert analysis.price_position == "premium"
    assert analysis.confidence == 0.9


def test_pricing_analysis_confidence_validation():
    """Test that confidence is validated."""
    # Valid confidence
    analysis = PricingAnalysis(
        competitor_avg_price=50.0,
        recommended_price=55.0,
        price_position="premium",
        confidence=0.5,
        reasoning="Test",
    )
    assert analysis.confidence == 0.5

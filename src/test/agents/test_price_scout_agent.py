"""
Unit tests for PriceScoutAgent.

Tests Smart Price Discovery flow: Google Shopping fetch, semantic filtering,
market metrics calculation, and pricing recommendations.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.main.agents.price_scout import PriceScoutAgent
from src.main.agents.price_scout.schemas import (
    PricingAnalysis,
    FilteredCompetitorsResponse,
)
from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for testing with Google Shopping data."""
    services = MagicMock()
    
    # Mock SERP service - Google Shopping results with extracted_price
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {
            "title": "Premium Ceramic Bowl",
            "price": "$45.00",
            "extracted_price": 45.0,
            "source": "Etsy",
            "link": "https://etsy.com/item1",
            "thumbnail": "https://example.com/img1.jpg",
            "shipping": "Free shipping",
        },
        {
            "title": "Artisan Handmade Bowl",
            "price": "$55.00",
            "extracted_price": 55.0,
            "source": "Amazon",
            "link": "https://amazon.com/item2",
            "thumbnail": "https://example.com/img2.jpg",
            "shipping": "$4.99",
        },
        {
            "title": "Japanese Style Bowl",
            "price": "$40.00",
            "extracted_price": 40.0,
            "source": "Wayfair",
            "link": "https://wayfair.com/item3",
            "thumbnail": "https://example.com/img3.jpg",
            "shipping": None,
        },
    ])
    
    # Mock LLM service - both filter and analysis responses
    def mock_generate_structured(prompt, response_format, **kwargs):
        if response_format == FilteredCompetitorsResponse:
            return FilteredCompetitorsResponse(
                valid_competitor_indices=[0, 1, 2],
                reasoning="All competitors are relevant ceramic bowls.",
            )
        elif response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=46.67,
                recommended_price=50.0,
                price_position="competitive",
                confidence=0.85,
                reasoning="Based on filtered competitor analysis, pricing at $50 positions the product competitively.",
            )
        return MagicMock()
    
    services.llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    
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
# Tests: Perception Phase (Google Shopping Fetch)
# =============================================================================

@pytest.mark.asyncio
async def test_perceive_fetches_shopping_results(mock_services, mission_state):
    """Test that perception fetches competitor data via Google Shopping."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    context = await agent.perceive(mission_state)
    
    # Should have called SERP service with num_results=20
    mock_services.serp.get_competitor_prices.assert_called_once()
    call_args = mock_services.serp.get_competitor_prices.call_args
    assert call_args.kwargs.get("num_results") == 20
    
    # Should have raw competitors in context (new field name)
    assert "raw_competitors" in context.external_data
    assert len(context.external_data["raw_competitors"]) == 3
    assert context.external_data["raw_competitor_count"] == 3


@pytest.mark.asyncio
async def test_perceive_handles_empty_competitors(mock_services, mission_state):
    """Test that perception handles no competitor data."""
    mock_services.serp.get_competitor_prices = AsyncMock(return_value=[])
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should have empty raw_competitors
    assert context.external_data["raw_competitors"] == []
    assert context.external_data["raw_competitor_count"] == 0


@pytest.mark.asyncio
async def test_perceive_handles_serp_error(mock_services, mission_state):
    """Test that perception handles SERP errors gracefully."""
    mock_services.serp.get_competitor_prices = AsyncMock(side_effect=Exception("SERP error"))
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should have empty raw_competitors on error
    assert context.external_data["raw_competitors"] == []
    assert context.external_data["raw_competitor_count"] == 0


# =============================================================================
# Tests: Action Phase (Semantic Filtering + Pricing Analysis)
# =============================================================================

@pytest.mark.asyncio
async def test_act_generates_pricing_analysis(mock_services, mission_state):
    """Test that action generates pricing analysis with new structure."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should have pricing analysis with new fields
    assert result.pricing_analysis is not None
    assert "competitor_avg_price" in result.pricing_analysis
    assert "recommended_price" in result.pricing_analysis
    assert "valid_competitors" in result.pricing_analysis
    assert "market_analysis" in result.pricing_analysis
    assert "filter_reasoning" in result.pricing_analysis


@pytest.mark.asyncio
async def test_act_makes_two_llm_calls(mock_services, mission_state):
    """Test that action makes 2 LLM calls: filter + analysis."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state)
    
    # Should have called generate_structured twice
    assert mock_services.llm.generate_structured.call_count == 2
    
    # First call should be FilteredCompetitorsResponse
    first_call = mock_services.llm.generate_structured.call_args_list[0]
    assert first_call.kwargs["response_format"] == FilteredCompetitorsResponse
    
    # Second call should be PricingAnalysis
    second_call = mock_services.llm.generate_structured.call_args_list[1]
    assert second_call.kwargs["response_format"] == PricingAnalysis


@pytest.mark.asyncio
async def test_act_uses_gpt4o_mini(mock_services, mission_state):
    """Test that action uses cheaper gpt-4o-mini model for both calls."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state)
    
    for call in mock_services.llm.generate_structured.call_args_list:
        assert call.kwargs.get("model") == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_act_skips_llm_without_competitors(mock_services, mission_state):
    """Test that action skips LLM calls when no competitors."""
    mock_services.serp.get_competitor_prices = AsyncMock(return_value=[])
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should NOT have called LLM
    mock_services.llm.generate_structured.assert_not_called()
    
    # Should still have pricing analysis (empty)
    assert result.pricing_analysis is not None
    assert result.pricing_analysis["competitor_count"] == 0
    assert result.pricing_analysis["confidence"] == 0.0
    assert result.pricing_analysis["valid_competitors"] == []


# =============================================================================
# Tests: Semantic Filtering
# =============================================================================

@pytest.mark.asyncio
async def test_semantic_filtering_filters_competitors(mock_services, mission_state):
    """Test that semantic filtering correctly filters competitors."""
    # Mock filter to only keep indices 0 and 2
    def mock_generate_structured(prompt, response_format, **kwargs):
        if response_format == FilteredCompetitorsResponse:
            return FilteredCompetitorsResponse(
                valid_competitor_indices=[0, 2],  # Skip index 1
                reasoning="Index 1 is not relevant.",
            )
        elif response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=42.5,
                recommended_price=45.0,
                price_position="competitive",
                confidence=0.80,
                reasoning="Based on 2 competitors.",
            )
        return MagicMock()
    
    mock_services.llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should have 2 valid competitors
    assert len(result.pricing_analysis["valid_competitors"]) == 2


@pytest.mark.asyncio
async def test_semantic_filtering_fallback_on_error(mock_services, mission_state):
    """Test that filtering falls back to raw results on error."""
    call_count = [0]
    
    def mock_generate_structured(prompt, response_format, **kwargs):
        call_count[0] += 1
        if response_format == FilteredCompetitorsResponse:
            raise Exception("Filtering failed")
        elif response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=46.67,
                recommended_price=50.0,
                price_position="competitive",
                confidence=0.6,
                reasoning="Analysis after filter fallback.",
            )
        return MagicMock()
    
    mock_services.llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should still have valid competitors (fallback to raw)
    assert len(result.pricing_analysis["valid_competitors"]) > 0
    assert "filter fallback" in result.pricing_analysis["filter_reasoning"].lower() or "error" in result.pricing_analysis["filter_reasoning"].lower()


# =============================================================================
# Tests: Market Metrics Calculation
# =============================================================================

@pytest.mark.asyncio
async def test_market_metrics_calculated_correctly(mock_services, mission_state):
    """Test that market metrics are calculated from filtered competitors."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    market_analysis = result.pricing_analysis["market_analysis"]
    
    # With prices [45.0, 55.0, 40.0]
    assert market_analysis["min_price"] == 40.0
    assert market_analysis["max_price"] == 55.0
    assert market_analysis["average_price"] == pytest.approx(46.67, rel=0.01)
    assert market_analysis["median_price"] == 45.0
    assert market_analysis["competitor_count"] == 3


def test_calculate_market_metrics_method():
    """Test _calculate_market_metrics method directly."""
    agent = PriceScoutAgent("test-shop", MagicMock())
    
    competitors = [
        {"extracted_price": 100.0},
        {"extracted_price": 200.0},
        {"extracted_price": 300.0},
        {"extracted_price": 400.0},
    ]
    
    metrics = agent._calculate_market_metrics(competitors)
    
    assert metrics["min_price"] == 100.0
    assert metrics["max_price"] == 400.0
    assert metrics["average_price"] == 250.0
    assert metrics["median_price"] == 250.0  # median of [100, 200, 300, 400]
    assert metrics["competitor_count"] == 4


def test_calculate_market_metrics_handles_missing_prices():
    """Test that metrics calculation handles missing extracted_price."""
    agent = PriceScoutAgent("test-shop", MagicMock())
    
    competitors = [
        {"extracted_price": 100.0},
        {"extracted_price": None},  # Missing
        {"extracted_price": 0},  # Zero (invalid)
        {"extracted_price": 200.0},
    ]
    
    metrics = agent._calculate_market_metrics(competitors)
    
    # Should only use valid prices [100.0, 200.0]
    assert metrics["min_price"] == 100.0
    assert metrics["max_price"] == 200.0
    assert metrics["competitor_count"] == 2


def test_calculate_market_metrics_empty_list():
    """Test metrics calculation with empty competitor list."""
    agent = PriceScoutAgent("test-shop", MagicMock())
    
    metrics = agent._calculate_market_metrics([])
    
    assert metrics["min_price"] == 0.0
    assert metrics["max_price"] == 0.0
    assert metrics["average_price"] == 0.0
    assert metrics["competitor_count"] == 0


# =============================================================================
# Tests: Structured Output Parsing
# =============================================================================

@pytest.mark.asyncio
async def test_pricing_analysis_structure(mock_services, mission_state):
    """Test that pricing analysis has expected structure."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    analysis = result.pricing_analysis
    
    # Check all expected fields (including new ones)
    assert "competitor_avg_price" in analysis
    assert "recommended_price" in analysis
    assert "price_position" in analysis
    assert "confidence" in analysis
    assert "reasoning" in analysis
    assert "competitor_count" in analysis
    # New Smart Price Discovery fields
    assert "valid_competitors" in analysis
    assert "market_analysis" in analysis
    assert "filter_reasoning" in analysis
    assert "raw_competitor_count" in analysis


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
async def test_handles_llm_error_gracefully(mock_services, mission_state):
    """Test that agent handles LLM errors with fallback pricing."""
    mock_services.llm.generate_structured = AsyncMock(side_effect=Exception("LLM error"))
    
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should complete with fallback analysis (not None)
    assert result.pricing_analysis is not None
    # Should have low confidence on fallback
    assert result.pricing_analysis["confidence"] <= 0.5
    # Should indicate error in reasoning or filter_reasoning
    assert "error" in result.pricing_analysis["filter_reasoning"].lower() or \
           "error" in result.pricing_analysis["reasoning"].lower()


# =============================================================================
# Tests: Prompt Building (Legacy compatibility)
# =============================================================================

def test_build_analysis_prompt():
    """Test that legacy analysis prompt is built correctly."""
    agent = PriceScoutAgent("test-shop", MagicMock())
    
    competitors = [
        {"title": "Product A", "snippet": "Snippet A", "price": "$50"},
        {"title": "Product B", "snippet": "Snippet B", "price": "$60"},
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
    """Test that legacy prompt limits to 5 competitors."""
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
    analysis = PricingAnalysis(
        competitor_avg_price=50.0,
        recommended_price=55.0,
        price_position="premium",
        confidence=0.5,
        reasoning="Test",
    )
    assert analysis.confidence == 0.5


def test_filtered_competitors_response_schema():
    """Test FilteredCompetitorsResponse Pydantic schema."""
    response = FilteredCompetitorsResponse(
        valid_competitor_indices=[0, 2, 5],
        reasoning="Kept indices 0, 2, 5 as true comparables.",
    )
    
    assert response.valid_competitor_indices == [0, 2, 5]
    assert "0, 2, 5" in response.reasoning


# =============================================================================
# Tests: Valid Competitors Structure
# =============================================================================

@pytest.mark.asyncio
async def test_valid_competitors_have_structured_data(mock_services, mission_state):
    """Test that valid_competitors have Google Shopping structured data."""
    agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    valid_competitors = result.pricing_analysis["valid_competitors"]
    
    # Check first competitor has all expected fields
    first_competitor = valid_competitors[0]
    assert "title" in first_competitor
    assert "price" in first_competitor
    assert "extracted_price" in first_competitor
    assert "source" in first_competitor
    assert "link" in first_competitor

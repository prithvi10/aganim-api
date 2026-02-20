"""
Integration tests for Smart Price Discovery feature.

Tests Google Shopping API integration, semantic filtering, market metrics
calculation, and error handling scenarios.
"""

import os
import pytest
import asyncio
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.price_scout import PriceScoutAgent
from src.ecommerce.agents.price_scout.schemas import (
    PricingAnalysis,
    FilteredCompetitorsResponse,
    MarketAnalysis,
    ShoppingCompetitor,
)
from src.ecommerce.state import MissionState
from src.ecommerce.orchestrator import MissionControl
from src.agentic_core.tools.serp_service import SerpService, ShoppingResult


# =============================================================================
# Fixtures: Mission State
# =============================================================================

@pytest.fixture
def mission_state():
    """Create a MissionState for testing."""
    return MissionState(
        product_id="test-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Standard",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "description": "Made in Kyoto using traditional techniques. Premium artisan quality.",
            "category": "Kitchenware",
        },
        target_locale="en",
    )


# =============================================================================
# Fixtures: Mock Services with Various Scenarios
# =============================================================================

@pytest.fixture
def mock_services_google_shopping_success():
    """Mock services with successful Google Shopping response."""
    services = MagicMock()
    
    # Google Shopping results with full structured data
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {
            "title": "Premium Artisan Ceramic Bowl",
            "price": "$48.00",
            "extracted_price": 48.0,
            "source": "Etsy",
            "link": "https://etsy.com/listing/123",
            "thumbnail": "https://img.etsy.com/bowl1.jpg",
            "shipping": "Free shipping",
        },
        {
            "title": "Handmade Japanese Bowl Set",
            "price": "$55.00",
            "extracted_price": 55.0,
            "source": "Amazon",
            "link": "https://amazon.com/dp/B123",
            "thumbnail": "https://images.amazon.com/bowl2.jpg",
            "shipping": "$5.99",
        },
        {
            "title": "Cheap Plastic Bowl 10-Pack",
            "price": "$12.99",
            "extracted_price": 12.99,
            "source": "Walmart",
            "link": "https://walmart.com/bowl3",
            "thumbnail": None,
            "shipping": "Free",
        },
        {
            "title": "Traditional Kyoto Ceramics",
            "price": "$62.00",
            "extracted_price": 62.0,
            "source": "JapanCrafts",
            "link": "https://japancrafts.com/item",
            "thumbnail": "https://japancrafts.com/img.jpg",
            "shipping": None,
        },
        {
            "title": "Stoneware Mixing Bowl",
            "price": "$35.00",
            "extracted_price": 35.0,
            "source": "Williams Sonoma",
            "link": "https://williams-sonoma.com/bowl",
            "thumbnail": "https://ws.com/bowl.jpg",
            "shipping": "$8.00",
        },
    ])
    
    # Mock LLM for filtering and analysis
    def mock_generate_structured(prompt, response_format, **kwargs):
        if response_format == FilteredCompetitorsResponse:
            # Filter out the cheap plastic bowl (index 2)
            return FilteredCompetitorsResponse(
                valid_competitor_indices=[0, 1, 3, 4],
                reasoning="Kept artisan/premium items. Discarded index 2 (cheap plastic bulk pack).",
            )
        elif response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=50.0,
                recommended_price=52.0,
                price_position="competitive",
                confidence=0.85,
                reasoning="Based on 4 filtered premium competitors, $52 is competitive.",
            )
        return MagicMock()
    
    services.llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mock_services_serp_timeout():
    """Mock services with SERP API timeout."""
    services = MagicMock()
    
    # SERP timeout
    async def serp_timeout(*args, **kwargs):
        raise asyncio.TimeoutError("Google Shopping API timeout after 10 seconds")
    
    services.serp.get_competitor_prices = AsyncMock(side_effect=serp_timeout)
    services.llm.generate_structured = AsyncMock()
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mock_services_serp_http_error():
    """Mock services with SERP API HTTP error."""
    services = MagicMock()
    
    # SERP HTTP error (rate limit, server error, etc.)
    async def serp_http_error(*args, **kwargs):
        raise httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=MagicMock(status_code=429),
        )
    
    services.serp.get_competitor_prices = AsyncMock(side_effect=serp_http_error)
    services.llm.generate_structured = AsyncMock()
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mock_services_serp_empty():
    """Mock services with empty SERP results."""
    services = MagicMock()
    
    # Empty results
    services.serp.get_competitor_prices = AsyncMock(return_value=[])
    services.llm.generate_structured = AsyncMock()
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mock_services_filter_fails():
    """Mock services where semantic filtering fails."""
    services = MagicMock()
    
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {"title": "Comp 1", "price": "$50.00", "extracted_price": 50.0, "source": "Etsy", "link": "https://etsy.com"},
        {"title": "Comp 2", "price": "$60.00", "extracted_price": 60.0, "source": "Amazon", "link": "https://amazon.com"},
    ])
    
    # First LLM call (filtering) fails, second (analysis) succeeds
    call_count = [0]
    def mock_generate_structured(prompt, response_format, **kwargs):
        call_count[0] += 1
        if response_format == FilteredCompetitorsResponse:
            raise Exception("LLM filtering failed: Rate limit exceeded")
        elif response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=55.0,
                recommended_price=55.0,
                price_position="competitive",
                confidence=0.6,
                reasoning="Analysis with fallback data.",
            )
        return MagicMock()
    
    services.llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mock_services_all_filtered_out():
    """Mock services where semantic filtering removes all competitors."""
    services = MagicMock()
    
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {"title": "Wrong Category Item", "price": "$20.00", "extracted_price": 20.0, "source": "Random", "link": ""},
        {"title": "Completely Irrelevant", "price": "$15.00", "extracted_price": 15.0, "source": "Other", "link": ""},
    ])
    
    def mock_generate_structured(prompt, response_format, **kwargs):
        if response_format == FilteredCompetitorsResponse:
            # Filter removes ALL
            return FilteredCompetitorsResponse(
                valid_competitor_indices=[],
                reasoning="All items are irrelevant to artisan ceramics.",
            )
        elif response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=17.5,
                recommended_price=45.0,
                price_position="premium",
                confidence=0.4,
                reasoning="Using fallback data, recommend premium positioning.",
            )
        return MagicMock()
    
    services.llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mock_services_missing_prices():
    """Mock services with competitors missing extracted_price."""
    services = MagicMock()
    
    # Some items missing extracted_price
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {"title": "Valid Comp", "price": "$50.00", "extracted_price": 50.0, "source": "Etsy", "link": ""},
        {"title": "No Price Comp", "price": "Contact for price", "extracted_price": None, "source": "Custom", "link": ""},
        {"title": "Zero Price", "price": "$0.00", "extracted_price": 0.0, "source": "Free", "link": ""},
        {"title": "Another Valid", "price": "$70.00", "extracted_price": 70.0, "source": "Premium", "link": ""},
    ])
    
    def mock_generate_structured(prompt, response_format, **kwargs):
        if response_format == FilteredCompetitorsResponse:
            return FilteredCompetitorsResponse(
                valid_competitor_indices=[0, 1, 2, 3],
                reasoning="Keeping all for analysis.",
            )
        elif response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=60.0,
                recommended_price=60.0,
                price_position="competitive",
                confidence=0.7,
                reasoning="Based on valid prices.",
            )
        return MagicMock()
    
    services.llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mock_services_both_llm_fail():
    """Mock services where both LLM calls fail."""
    services = MagicMock()
    
    services.serp.get_competitor_prices = AsyncMock(return_value=[
        {"title": "Comp 1", "price": "$50.00", "extracted_price": 50.0, "source": "Etsy", "link": ""},
        {"title": "Comp 2", "price": "$60.00", "extracted_price": 60.0, "source": "Amazon", "link": ""},
    ])
    
    # Both LLM calls fail
    services.llm.generate_structured = AsyncMock(side_effect=Exception("LLM service unavailable"))
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


# =============================================================================
# Tests: Google Shopping Integration Success
# =============================================================================

class TestGoogleShoppingIntegration:
    """Tests for successful Google Shopping API integration."""

    @pytest.mark.asyncio
    async def test_fetches_shopping_results(self, mock_services_google_shopping_success, mission_state):
        """Test that agent fetches Google Shopping results."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        await agent.run(mission_state)
        
        # Should call get_competitor_prices with num_results=20
        mock_services_google_shopping_success.serp.get_competitor_prices.assert_called_once()
        call_kwargs = mock_services_google_shopping_success.serp.get_competitor_prices.call_args.kwargs
        assert call_kwargs.get("num_results") == 20

    @pytest.mark.asyncio
    async def test_shopping_results_have_structured_data(self, mock_services_google_shopping_success, mission_state):
        """Test that shopping results include structured price data."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        result = await agent.run(mission_state)
        
        # Valid competitors should have structured data
        valid_competitors = result.pricing_analysis.get("valid_competitors", [])
        assert len(valid_competitors) > 0
        
        first = valid_competitors[0]
        assert "title" in first
        assert "price" in first
        assert "extracted_price" in first
        assert "source" in first
        assert "link" in first

    @pytest.mark.asyncio
    async def test_semantic_filter_removes_irrelevant(self, mock_services_google_shopping_success, mission_state):
        """Test that semantic filtering removes irrelevant items."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        result = await agent.run(mission_state)
        
        # Should have fewer valid competitors than raw (filtered out cheap plastic)
        raw_count = result.pricing_analysis.get("raw_competitor_count", 0)
        valid_count = len(result.pricing_analysis.get("valid_competitors", []))
        
        assert raw_count == 5
        assert valid_count == 4  # Filtered out the cheap plastic bulk pack

    @pytest.mark.asyncio
    async def test_market_metrics_calculated(self, mock_services_google_shopping_success, mission_state):
        """Test that market metrics are calculated from filtered competitors."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        result = await agent.run(mission_state)
        
        market_analysis = result.pricing_analysis.get("market_analysis", {})
        
        assert "min_price" in market_analysis
        assert "max_price" in market_analysis
        assert "average_price" in market_analysis
        assert "median_price" in market_analysis
        assert "competitor_count" in market_analysis
        
        # Metrics should be reasonable
        assert market_analysis["min_price"] > 0
        assert market_analysis["max_price"] >= market_analysis["min_price"]
        assert market_analysis["average_price"] >= market_analysis["min_price"]

    @pytest.mark.asyncio
    async def test_filter_reasoning_stored(self, mock_services_google_shopping_success, mission_state):
        """Test that filter reasoning is stored in state."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        result = await agent.run(mission_state)
        
        filter_reasoning = result.pricing_analysis.get("filter_reasoning", "")
        assert len(filter_reasoning) > 0
        assert "plastic" in filter_reasoning.lower() or "discarded" in filter_reasoning.lower()

    @pytest.mark.asyncio
    async def test_two_llm_calls_made(self, mock_services_google_shopping_success, mission_state):
        """Test that exactly 2 LLM calls are made (filter + analysis)."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        await agent.run(mission_state)
        
        assert mock_services_google_shopping_success.llm.generate_structured.call_count == 2


# =============================================================================
# Tests: SERP API Failures
# =============================================================================

class TestSerpApiFailures:
    """Tests for SERP API failure scenarios."""

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_analysis(self, mock_services_serp_timeout, mission_state):
        """Test that SERP timeout returns empty analysis."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_serp_timeout)
        result = await agent.run(mission_state)
        
        assert result.pricing_analysis is not None
        assert result.pricing_analysis["competitor_count"] == 0
        assert result.pricing_analysis["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_timeout_skips_llm_calls(self, mock_services_serp_timeout, mission_state):
        """Test that SERP timeout skips all LLM calls."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_serp_timeout)
        await agent.run(mission_state)
        
        # No LLM calls when no competitors
        mock_services_serp_timeout.llm.generate_structured.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_does_not_crash(self, mock_services_serp_timeout, mission_state):
        """Test that SERP timeout does not crash the agent."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_serp_timeout)
        result = await agent.run(mission_state)
        
        assert result is not None
        assert result.status != "ERROR"

    @pytest.mark.asyncio
    async def test_http_error_handled_gracefully(self, mock_services_serp_http_error, mission_state):
        """Test that HTTP errors are handled gracefully."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_serp_http_error)
        result = await agent.run(mission_state)
        
        assert result is not None
        assert result.pricing_analysis is not None
        assert result.pricing_analysis["competitor_count"] == 0

    @pytest.mark.asyncio
    async def test_empty_results_handled(self, mock_services_serp_empty, mission_state):
        """Test that empty SERP results are handled."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_serp_empty)
        result = await agent.run(mission_state)
        
        assert result.pricing_analysis["valid_competitors"] == []
        assert result.pricing_analysis["market_analysis"] is None
        assert "No competitor" in result.pricing_analysis.get("filter_reasoning", "") or \
               "fetched" in result.pricing_analysis.get("filter_reasoning", "").lower()


# =============================================================================
# Tests: Semantic Filtering Failures
# =============================================================================

class TestSemanticFilteringFailures:
    """Tests for semantic filtering failure scenarios."""

    @pytest.mark.asyncio
    async def test_filter_failure_uses_fallback(self, mock_services_filter_fails, mission_state):
        """Test that filtering failure falls back to raw results."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_filter_fails)
        result = await agent.run(mission_state)
        
        # Should still have valid competitors (fallback)
        assert len(result.pricing_analysis["valid_competitors"]) > 0
        
        # Reasoning should mention error/fallback
        filter_reasoning = result.pricing_analysis.get("filter_reasoning", "")
        assert "error" in filter_reasoning.lower() or "failed" in filter_reasoning.lower()

    @pytest.mark.asyncio
    async def test_all_filtered_uses_fallback(self, mock_services_all_filtered_out, mission_state):
        """Test that all-filtered-out scenario uses fallback."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_all_filtered_out)
        result = await agent.run(mission_state)
        
        # Should use fallback (top raw results)
        assert len(result.pricing_analysis["valid_competitors"]) > 0
        
        # Reasoning should mention fallback
        filter_reasoning = result.pricing_analysis.get("filter_reasoning", "")
        assert "fallback" in filter_reasoning.lower() or "irrelevant" in filter_reasoning.lower()

    @pytest.mark.asyncio
    async def test_both_llm_fail_returns_fallback_analysis(self, mock_services_both_llm_fail, mission_state):
        """Test that both LLM failures return fallback analysis."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_both_llm_fail)
        result = await agent.run(mission_state)
        
        # Should still have analysis with low confidence
        assert result.pricing_analysis is not None
        assert result.pricing_analysis["confidence"] <= 0.5
        
        # Should have error in reasoning
        reasoning = result.pricing_analysis.get("reasoning", "")
        filter_reasoning = result.pricing_analysis.get("filter_reasoning", "")
        assert "error" in reasoning.lower() or "error" in filter_reasoning.lower()


# =============================================================================
# Tests: Market Metrics Edge Cases
# =============================================================================

class TestMarketMetricsEdgeCases:
    """Tests for market metrics calculation edge cases."""

    @pytest.mark.asyncio
    async def test_missing_prices_excluded(self, mock_services_missing_prices, mission_state):
        """Test that items with missing extracted_price are excluded from metrics."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_missing_prices)
        result = await agent.run(mission_state)
        
        market_analysis = result.pricing_analysis.get("market_analysis", {})
        
        # Should only use valid prices (50 and 70), not None or 0
        # With fallback to all competitors, metrics should be calculated from valid prices only
        assert market_analysis["competitor_count"] == 2  # Only valid prices
        assert market_analysis["min_price"] == 50.0
        assert market_analysis["max_price"] == 70.0

    @pytest.mark.asyncio
    async def test_single_competitor_metrics(self, mock_services_google_shopping_success, mission_state):
        """Test metrics calculation with single competitor."""
        # Override to return single competitor
        mock_services_google_shopping_success.serp.get_competitor_prices = AsyncMock(return_value=[
            {"title": "Only Comp", "price": "$50.00", "extracted_price": 50.0, "source": "Etsy", "link": ""},
        ])
        
        def mock_generate_structured(prompt, response_format, **kwargs):
            if response_format == FilteredCompetitorsResponse:
                return FilteredCompetitorsResponse(valid_competitor_indices=[0], reasoning="Only one competitor.")
            elif response_format == PricingAnalysis:
                return PricingAnalysis(
                    competitor_avg_price=50.0,
                    recommended_price=50.0,
                    price_position="competitive",
                    confidence=0.5,
                    reasoning="Limited data.",
                )
            return MagicMock()
        
        mock_services_google_shopping_success.llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        result = await agent.run(mission_state)
        
        market_analysis = result.pricing_analysis.get("market_analysis", {})
        
        # Single competitor: min = max = avg = median
        assert market_analysis["min_price"] == 50.0
        assert market_analysis["max_price"] == 50.0
        assert market_analysis["average_price"] == 50.0
        assert market_analysis["median_price"] == 50.0
        assert market_analysis["competitor_count"] == 1


# =============================================================================
# Tests: Full Pipeline Integration
# =============================================================================

class TestFullPipelineIntegration:
    """Tests for full pipeline with Smart Price Discovery."""

    @pytest.mark.asyncio
    async def test_pipeline_completes_with_shopping_data(self, mock_services_google_shopping_success, mission_state):
        """Test that full pipeline completes with Google Shopping data."""
        # Add mock for other agents
        mock_services_google_shopping_success.llm.generate_text = AsyncMock(return_value="""{
            "title": "Beautiful Ceramic Bowl",
            "description": "<p>Handcrafted ceramic bowl</p>",
            "discovered_values": []
        }""")
        
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services_google_shopping_success,
        )
        
        final_state = None
        async for state in mission.execute(mission_state):
            final_state = state
        
        assert final_state.status == "COMPLETED"
        assert final_state.pricing_analysis is not None

    @pytest.mark.asyncio
    async def test_pipeline_completes_with_serp_failure(self, mock_services_serp_timeout, mission_state):
        """Test that pipeline completes even with SERP failure."""
        # Add mock for other agents
        mock_services_serp_timeout.llm.generate_text = AsyncMock(return_value="""{
            "title": "Test Bowl",
            "description": "<p>Test</p>"
        }""")
        
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services_serp_timeout,
        )
        
        final_state = None
        async for state in mission.execute(mission_state):
            final_state = state
        
        assert final_state.status == "COMPLETED"
        # Pricing analysis should exist but be empty
        assert final_state.pricing_analysis["competitor_count"] == 0


# =============================================================================
# Tests: Output Structure Validation
# =============================================================================

class TestOutputStructureValidation:
    """Tests for output structure validation."""

    @pytest.mark.asyncio
    async def test_success_output_structure(self, mock_services_google_shopping_success, mission_state):
        """Test output structure on success."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        result = await agent.run(mission_state)
        
        pricing = result.pricing_analysis
        
        # Core fields
        assert "competitor_avg_price" in pricing
        assert "recommended_price" in pricing
        assert "price_position" in pricing
        assert "confidence" in pricing
        assert "reasoning" in pricing
        assert "competitor_count" in pricing
        
        # Smart Price Discovery fields
        assert "valid_competitors" in pricing
        assert "market_analysis" in pricing
        assert "filter_reasoning" in pricing
        assert "raw_competitor_count" in pricing

    @pytest.mark.asyncio
    async def test_failure_output_structure(self, mock_services_serp_timeout, mission_state):
        """Test output structure on failure."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_serp_timeout)
        result = await agent.run(mission_state)
        
        pricing = result.pricing_analysis
        
        # All fields should exist even on failure
        assert "competitor_avg_price" in pricing
        assert "recommended_price" in pricing
        assert "price_position" in pricing
        assert "confidence" in pricing
        assert "reasoning" in pricing
        assert "competitor_count" in pricing
        assert "valid_competitors" in pricing
        assert "filter_reasoning" in pricing

    @pytest.mark.asyncio
    async def test_valid_competitor_structure(self, mock_services_google_shopping_success, mission_state):
        """Test valid_competitors item structure."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_google_shopping_success)
        result = await agent.run(mission_state)
        
        valid_competitors = result.pricing_analysis["valid_competitors"]
        
        for comp in valid_competitors:
            assert "title" in comp
            assert "price" in comp
            assert "extracted_price" in comp
            assert "source" in comp
            assert "link" in comp


# =============================================================================
# Tests: Schema Validation
# =============================================================================

class TestSchemaValidation:
    """Tests for Pydantic schema validation."""

    def test_shopping_competitor_schema(self):
        """Test ShoppingCompetitor schema."""
        comp = ShoppingCompetitor(
            title="Test Product",
            price="$50.00",
            extracted_price=50.0,
            source="Amazon",
            link="https://amazon.com/product",
            thumbnail="https://img.amazon.com/img.jpg",
            shipping="Free shipping",
        )
        
        assert comp.title == "Test Product"
        assert comp.extracted_price == 50.0
        assert comp.is_relevant == True  # Default

    def test_filtered_competitors_response_schema(self):
        """Test FilteredCompetitorsResponse schema."""
        response = FilteredCompetitorsResponse(
            valid_competitor_indices=[0, 2, 4],
            reasoning="Kept relevant competitors.",
        )
        
        assert len(response.valid_competitor_indices) == 3
        assert 2 in response.valid_competitor_indices

    def test_market_analysis_schema(self):
        """Test MarketAnalysis schema."""
        analysis = MarketAnalysis(
            min_price=30.0,
            max_price=80.0,
            average_price=55.0,
            median_price=52.0,
            competitor_count=5,
        )
        
        assert analysis.min_price == 30.0
        assert analysis.max_price == 80.0
        assert analysis.average_price == 55.0
        assert analysis.median_price == 52.0
        assert analysis.competitor_count == 5


# =============================================================================
# Tests: SerpService Unit Tests
# =============================================================================

class TestSerpServiceShoppingMethod:
    """Unit tests for SerpService.search_shopping method."""

    @pytest.mark.asyncio
    async def test_search_shopping_empty_query(self):
        """Test search_shopping with empty query."""
        service = SerpService(api_key="test-key")
        result = await service.search_shopping("")
        
        assert result == []

    @pytest.mark.asyncio
    async def test_search_shopping_no_api_key(self):
        """Test search_shopping without API key."""
        # Explicitly pass None and clear env to ensure no API key is used
        with patch.dict('os.environ', {'SERP_API_KEY': ''}, clear=False), \
             patch('src.agentic_core.tools.serp_service.SERP_API_KEY', None):
            service = SerpService(api_key=None)
            result = await service.search_shopping("test query")
            
            assert result == []

    def test_shopping_result_dataclass(self):
        """Test ShoppingResult dataclass."""
        result = ShoppingResult(
            title="Test Product",
            price="$45.00",
            extracted_price=45.0,
            source="Etsy",
            link="https://etsy.com/listing",
            thumbnail="https://img.etsy.com/img.jpg",
            shipping="Free",
            position=1,
        )
        
        assert result.title == "Test Product"
        assert result.extracted_price == 45.0
        assert result.source == "Etsy"
        assert result.position == 1

    def test_shopping_result_optional_fields(self):
        """Test ShoppingResult with optional fields as None."""
        result = ShoppingResult(
            title="Test",
            price="$50.00",
            extracted_price=50.0,
            source="Amazon",
            link="https://amazon.com",
            thumbnail=None,
            shipping=None,
        )
        
        assert result.thumbnail is None
        assert result.shipping is None
        assert result.position == 0  # Default


# =============================================================================
# Tests: Concurrency and Race Conditions
# =============================================================================

class TestConcurrencyScenarios:
    """Tests for concurrency scenarios."""

    @pytest.mark.asyncio
    async def test_multiple_agents_concurrent(self, mock_services_google_shopping_success, mission_state):
        """Test running multiple PriceScoutAgents concurrently."""
        agent1 = PriceScoutAgent("shop1.myshopify.com", mock_services_google_shopping_success)
        agent2 = PriceScoutAgent("shop2.myshopify.com", mock_services_google_shopping_success)
        
        # Run concurrently
        result1, result2 = await asyncio.gather(
            agent1.run(mission_state),
            agent2.run(mission_state),
        )
        
        # Both should complete successfully
        assert result1.pricing_analysis is not None
        assert result2.pricing_analysis is not None

    @pytest.mark.asyncio
    async def test_serp_timeout_does_not_block(self, mock_services_serp_timeout, mission_state):
        """Test that SERP timeout doesn't block indefinitely."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_serp_timeout)
        
        # Should complete within reasonable time (not hang)
        try:
            result = await asyncio.wait_for(agent.run(mission_state), timeout=5.0)
            assert result is not None
        except asyncio.TimeoutError:
            pytest.fail("Agent timed out - SERP timeout not handled properly")

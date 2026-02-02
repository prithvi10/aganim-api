"""
Integration tests for SERP API timeout handling.

Confirms that agents handle SERP API timeouts gracefully and produce
valid output even when SERP data is unavailable.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.main.agents.orchestrator import MissionControl
from src.main.agents.copywriter import CopywriterAgent
from src.main.agents.marketing import MarketingAgent
from src.main.agents.price_scout import PriceScoutAgent
from src.main.agents.compliance import ComplianceAgent
from src.main.agents.compliance.schemas import ComplianceCheck
from src.main.agents.price_scout.schemas import PricingAnalysis
from src.main.agents.state import MissionState


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services_with_serp_timeout():
    """Create mock ServiceRegistry with SERP timeout."""
    services = MagicMock()
    
    # Mock LLM - works normally
    services.llm.generate_text = AsyncMock(return_value="""{
        "title": "Test Title",
        "description": "<p>Test description</p>",
        "seo_title": "SEO Title",
        "seo_description": "SEO Description",
        "seo_alt_text": "Alt text",
        "discovered_values": []
    }""")
    
    async def mock_structured(*args, **kwargs):
        response_format = kwargs.get('response_format')
        if response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=0.0,
                recommended_price=0.0,
                price_position="unknown",
                confidence=0.0,
                reasoning="No competitor data available",
            )
        elif response_format == ComplianceCheck:
            return ComplianceCheck(
                has_violations=False,
                flags=[],
                severity="none",
                suggestions=[],
            )
        return MagicMock()
    
    services.llm.generate_structured = AsyncMock(side_effect=mock_structured)
    services.llm.generate_json = AsyncMock(return_value={})
    
    # Mock SERP - TIMEOUT ERROR
    async def serp_timeout(*args, **kwargs):
        raise asyncio.TimeoutError("SERP API timeout after 30 seconds")
    
    services.serp.search = AsyncMock(side_effect=serp_timeout)
    services.serp.get_competitor_prices = AsyncMock(side_effect=serp_timeout)
    
    # Mock RAG - works normally
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mock_services_with_serp_error():
    """Create mock ServiceRegistry with SERP connection error."""
    services = MagicMock()
    
    # Mock LLM - works normally
    services.llm.generate_text = AsyncMock(return_value="""{
        "title": "Test Title",
        "description": "<p>Test description</p>"
    }""")
    
    async def mock_structured(*args, **kwargs):
        response_format = kwargs.get('response_format')
        if response_format == PricingAnalysis:
            return PricingAnalysis(
                competitor_avg_price=0.0,
                recommended_price=0.0,
                price_position="unknown",
                confidence=0.0,
                reasoning="No competitor data",
            )
        elif response_format == ComplianceCheck:
            return ComplianceCheck(
                has_violations=False,
                flags=[],
                severity="none",
                suggestions=[],
            )
        return MagicMock()
    
    services.llm.generate_structured = AsyncMock(side_effect=mock_structured)
    services.llm.generate_json = AsyncMock(return_value={})
    
    # Mock SERP - CONNECTION ERROR
    async def serp_error(*args, **kwargs):
        raise ConnectionError("Unable to connect to SERP API")
    
    services.serp.search = AsyncMock(side_effect=serp_error)
    services.serp.get_competitor_prices = AsyncMock(side_effect=serp_error)
    
    # Mock RAG
    services.rag.get_brand_context = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mission_state():
    """Create a MissionState for testing."""
    return MissionState(
        product_id="test-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Standard",
        raw_input={
            "title": "Test Product",
            "description": "Test description",
            "category": "Kitchenware",
        },
        target_locale="en",
    )


# =============================================================================
# Tests: MarketingAgent SERP Timeout Handling
# =============================================================================

class TestMarketingAgentSerpTimeout:
    """Tests for MarketingAgent SERP timeout handling."""

    @pytest.mark.asyncio
    async def test_marketing_completes_on_serp_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that MarketingAgent completes even with SERP timeout."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # Should complete without crashing
        assert result is not None
        assert result.status != "ERROR"

    @pytest.mark.asyncio
    async def test_marketing_seo_generated_without_serp(self, mock_services_with_serp_timeout, mission_state):
        """Test that SEO is still generated without SERP data."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # SEO should still be generated (using LLM without competitor context)
        # Note: seo_title may be empty string if LLM fails to parse
        assert result.seo_description is not None or result.ctr_check is not None

    @pytest.mark.asyncio
    async def test_marketing_ctr_check_works_without_serp(self, mock_services_with_serp_timeout, mission_state):
        """Test that CTR check works without SERP data."""
        mission_state.draft_content = "<p>Test content with benefits</p>"
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # CTR check is deterministic, should work
        assert result.ctr_check is not None
        assert "score" in result.ctr_check

    @pytest.mark.asyncio
    async def test_marketing_serp_insights_empty_on_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that SERP insights are empty on timeout."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # SERP insights should be empty list
        assert result.serp_insights == [] or result.serp_insights is None


# =============================================================================
# Tests: PriceScoutAgent SERP Timeout Handling
# =============================================================================

class TestPriceScoutAgentSerpTimeout:
    """Tests for PriceScoutAgent SERP timeout handling."""

    @pytest.mark.asyncio
    async def test_pricescout_completes_on_serp_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that PriceScoutAgent completes even with SERP timeout."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # Should complete without crashing
        assert result is not None
        assert result.status != "ERROR"

    @pytest.mark.asyncio
    async def test_pricescout_returns_empty_analysis_on_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that PriceScout returns empty analysis on SERP timeout."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # Should have pricing_analysis with zero values
        assert result.pricing_analysis is not None
        assert result.pricing_analysis["competitor_count"] == 0
        assert result.pricing_analysis["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_pricescout_skips_llm_on_serp_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that PriceScout skips LLM call when SERP times out."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        await agent.run(mission_state)
        
        # Should NOT call LLM when no competitors available
        mock_services_with_serp_timeout.llm.generate_structured.assert_not_called()

    @pytest.mark.asyncio
    async def test_pricescout_price_position_unknown_on_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that price_position is 'unknown' on SERP timeout."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        assert result.pricing_analysis["price_position"] == "unknown"

    @pytest.mark.asyncio
    async def test_pricescout_reasoning_indicates_no_data(self, mock_services_with_serp_timeout, mission_state):
        """Test that reasoning indicates no competitor data."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # Reasoning should indicate no data
        reasoning = result.pricing_analysis.get("reasoning", "")
        assert "no" in reasoning.lower() or "competitor" in reasoning.lower() or len(reasoning) == 0


# =============================================================================
# Tests: Full Pipeline with SERP Timeout
# =============================================================================

class TestFullPipelineSerpTimeout:
    """Tests for full pipeline execution with SERP timeout."""

    @pytest.mark.asyncio
    async def test_pipeline_completes_with_serp_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that full pipeline completes even with SERP timeout."""
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services_with_serp_timeout,
        )
        
        final_state = None
        async for state in mission.execute(mission_state):
            final_state = state
        
        # Should complete successfully
        assert final_state.status in ["COMPLETED", "COMPLIANCE_REVIEW"]

    @pytest.mark.asyncio
    async def test_pipeline_all_agents_run_with_serp_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that all agents run even with SERP timeout."""
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services_with_serp_timeout,
        )
        
        all_logs = []
        async for state in mission.execute(mission_state):
            all_logs.extend(state.logs)
        
        logs_text = "\n".join(all_logs)
        
        # All agents should have run
        assert "Copywriter" in logs_text
        assert "Marketing" in logs_text
        assert "PriceScout" in logs_text
        assert "Compliance" in logs_text

    @pytest.mark.asyncio
    async def test_pipeline_draft_content_generated_with_serp_timeout(self, mock_services_with_serp_timeout, mission_state):
        """Test that draft content is generated despite SERP timeout."""
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services_with_serp_timeout,
        )
        
        final_state = None
        async for state in mission.execute(mission_state):
            final_state = state
        
        # Should have draft content from Copywriter
        assert final_state.draft_content is not None or final_state.draft_title is not None


# =============================================================================
# Tests: SERP Connection Error Handling
# =============================================================================

class TestSerpConnectionError:
    """Tests for SERP connection error handling."""

    @pytest.mark.asyncio
    async def test_marketing_handles_connection_error(self, mock_services_with_serp_error, mission_state):
        """Test that MarketingAgent handles connection error."""
        mission_state.draft_content = "<p>Test</p>"
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services_with_serp_error)
        result = await agent.run(mission_state)
        
        # Should complete without crashing
        assert result is not None
        assert result.status != "ERROR"

    @pytest.mark.asyncio
    async def test_pricescout_handles_connection_error(self, mock_services_with_serp_error, mission_state):
        """Test that PriceScoutAgent handles connection error."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_with_serp_error)
        result = await agent.run(mission_state)
        
        # Should complete with empty analysis
        assert result.pricing_analysis is not None
        assert result.pricing_analysis["competitor_count"] == 0

    @pytest.mark.asyncio
    async def test_pipeline_handles_connection_error(self, mock_services_with_serp_error, mission_state):
        """Test that full pipeline handles connection error."""
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services_with_serp_error,
        )
        
        final_state = None
        async for state in mission.execute(mission_state):
            final_state = state
        
        # Should complete successfully
        assert final_state.status in ["COMPLETED", "COMPLIANCE_REVIEW"]


# =============================================================================
# Tests: Output Structure with SERP Failure
# =============================================================================

class TestOutputStructureWithSerpFailure:
    """Tests for output structure validation when SERP fails."""

    @pytest.mark.asyncio
    async def test_marketing_output_structure_on_serp_failure(self, mock_services_with_serp_timeout, mission_state):
        """Test MarketingAgent output structure when SERP fails."""
        mission_state.draft_content = "<p>Test</p>"
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # Required fields should exist (even if empty)
        assert hasattr(result, 'seo_title')
        assert hasattr(result, 'seo_description')
        assert hasattr(result, 'seo_alt_text')
        assert hasattr(result, 'ctr_check')
        assert hasattr(result, 'serp_insights')

    @pytest.mark.asyncio
    async def test_pricescout_output_structure_on_serp_failure(self, mock_services_with_serp_timeout, mission_state):
        """Test PriceScoutAgent output structure when SERP fails."""
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services_with_serp_timeout)
        result = await agent.run(mission_state)
        
        # Required fields should exist
        assert result.pricing_analysis is not None
        assert "competitor_avg_price" in result.pricing_analysis
        assert "recommended_price" in result.pricing_analysis
        assert "price_position" in result.pricing_analysis
        assert "confidence" in result.pricing_analysis
        assert "competitor_count" in result.pricing_analysis

    @pytest.mark.asyncio
    async def test_state_serialization_with_serp_failure(self, mock_services_with_serp_timeout, mission_state):
        """Test that state can be serialized when SERP fails."""
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="test-shop.myshopify.com",
            services=mock_services_with_serp_timeout,
        )
        
        async for state in mission.execute(mission_state):
            # Each state should be serializable
            data = state.to_dict()
            assert isinstance(data, dict)
            assert "product_id" in data
            assert "status" in data

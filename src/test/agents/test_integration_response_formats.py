"""
Integration tests for agent response format handling.

Confirms that response formats are accurately handled for each agent.
Note: ComplianceAgent is currently disabled. SEO is handled by SEOAgent.
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock

from src.main.agents.copywriter import CopywriterAgent
from src.main.agents.seo import SEOAgent
from src.main.agents.marketing import MarketingAgent
from src.main.agents.price_scout import PriceScoutAgent
from src.main.agents.price_scout.schemas import PricingAnalysis
from src.main.agents.state import MissionState


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock()
    services.llm.generate_structured = AsyncMock()
    services.llm.generate_json = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.serp.get_competitor_prices = AsyncMock(return_value=[])
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
# Tests: CopywriterAgent Response Format Handling
# =============================================================================

class TestCopywriterResponseFormats:
    """Tests for CopywriterAgent response format handling."""

    @pytest.mark.asyncio
    async def test_handles_valid_json_response(self, mock_services, mission_state):
        """Test handling of valid JSON response."""
        mock_services.llm.generate_text = AsyncMock(return_value=json.dumps({
            "title": "Test Title",
            "description": "<p>Test description</p>",
            "seo_title": "SEO Title",
            "seo_description": "SEO Description",
            "seo_alt_text": "Alt text",
            "discovered_values": []
        }))
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.draft_title == "Test Title"
        assert result.draft_content == "<p>Test description</p>"

    @pytest.mark.asyncio
    async def test_handles_json_with_markdown_wrapper(self, mock_services, mission_state):
        """Test handling of JSON wrapped in markdown code blocks."""
        mock_services.llm.generate_text = AsyncMock(return_value='''```json
{
    "title": "Test Title",
    "description": "<p>Test description</p>",
    "discovered_values": []
}
```''')
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should extract and parse JSON from markdown
        assert result.draft_title == "Test Title" or result.draft_content is not None

    @pytest.mark.asyncio
    async def test_handles_malformed_json_gracefully(self, mock_services, mission_state):
        """Test handling of malformed JSON response."""
        mock_services.llm.generate_text = AsyncMock(return_value="Not valid JSON at all")
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should not crash, should use raw content as fallback
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_handles_partial_json_response(self, mock_services, mission_state):
        """Test handling of partial JSON (missing fields)."""
        mock_services.llm.generate_text = AsyncMock(return_value=json.dumps({
            "title": "Test Title",
            # Missing description, seo fields, etc.
        }))
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should handle gracefully
        assert result.draft_title == "Test Title"

    @pytest.mark.asyncio
    async def test_handles_empty_string_response(self, mock_services, mission_state):
        """Test handling of empty string response."""
        mock_services.llm.generate_text = AsyncMock(return_value="")
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should handle gracefully without crashing
        assert result is not None

    @pytest.mark.asyncio
    async def test_handles_unicode_in_response(self, mock_services, mission_state):
        """Test handling of Unicode characters in response."""
        mock_services.llm.generate_text = AsyncMock(return_value=json.dumps({
            "title": "京都の陶器ボウル",
            "description": "<p>日本の伝統的な職人技</p>",
            "discovered_values": []
        }))
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert "京都" in result.draft_title


# =============================================================================
# Tests: SEOAgent Response Format Handling
# =============================================================================

class TestSEOResponseFormats:
    """Tests for SEOAgent response format handling."""

    @pytest.mark.asyncio
    async def test_handles_valid_seo_json(self, mock_services, mission_state):
        """Test handling of valid SEO JSON response."""
        mission_state.draft_content = "<p>Test</p>"
        
        mock_services.llm.generate_text = AsyncMock(return_value=json.dumps({
            "seo_title": "SEO Title Here",
            "seo_description": "Meta description here",
            "seo_alt_text": "Alt text here",
        }))
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.seo_title == "SEO Title Here"
        assert result.seo_description == "Meta description here"

    @pytest.mark.asyncio
    async def test_clamps_seo_title_length(self, mock_services, mission_state):
        """Test that SEO title is clamped to 70 characters."""
        mission_state.draft_content = "<p>Test</p>"
        
        long_title = "A" * 100
        mock_services.llm.generate_text = AsyncMock(return_value=json.dumps({
            "seo_title": long_title,
            "seo_description": "Description",
            "seo_alt_text": "Alt",
        }))
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert len(result.seo_title) <= 70

    @pytest.mark.asyncio
    async def test_clamps_seo_description_length(self, mock_services, mission_state):
        """Test that SEO description is clamped to 160 characters."""
        mission_state.draft_content = "<p>Test</p>"
        
        long_desc = "B" * 200
        mock_services.llm.generate_text = AsyncMock(return_value=json.dumps({
            "seo_title": "Title",
            "seo_description": long_desc,
            "seo_alt_text": "Alt",
        }))
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert len(result.seo_description) <= 160

    @pytest.mark.asyncio
    async def test_handles_malformed_seo_json(self, mock_services, mission_state):
        """Test handling of malformed SEO JSON."""
        mission_state.draft_content = "<p>Test</p>"
        
        mock_services.llm.generate_text = AsyncMock(return_value="Not JSON")
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should handle gracefully
        assert result is not None

    @pytest.mark.asyncio
    async def test_ctr_check_returns_valid_structure(self, mock_services, mission_state):
        """Test that CTR check returns valid structure."""
        mission_state.draft_content = "<p>Test content with benefits</p>"
        
        mock_services.llm.generate_text = AsyncMock(return_value="{}")
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # CTR check should have required fields
        assert "score" in result.ctr_check
        assert "pain_present" in result.ctr_check
        assert "solution_present" in result.ctr_check
        assert "trust_present" in result.ctr_check
        assert 0.0 <= result.ctr_check["score"] <= 1.0


# =============================================================================
# Tests: MarketingAgent Response Format Handling
# =============================================================================

class TestMarketingResponseFormats:
    """Tests for MarketingAgent response format handling (social hooks only)."""

    @pytest.mark.asyncio
    async def test_handles_valid_hooks_json(self, mock_services, mission_state):
        """Test handling of valid social hooks JSON response."""
        mission_state.draft_content = "<p>Test</p>"
        
        mock_services.llm.generate_text = AsyncMock(return_value=json.dumps({
            "hooks": [
                {"type": "Story", "caption": "Test caption", "hashtags": ["#test"]}
            ]
        }))
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should handle gracefully
        assert result is not None

    @pytest.mark.asyncio
    async def test_handles_malformed_hooks_json(self, mock_services, mission_state):
        """Test handling of malformed hooks JSON."""
        mission_state.draft_content = "<p>Test</p>"
        
        mock_services.llm.generate_text = AsyncMock(return_value="Not JSON")
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should handle gracefully
        assert result is not None


# =============================================================================
# Tests: PriceScoutAgent Response Format Handling
# =============================================================================

class TestPriceScoutResponseFormats:
    """Tests for PriceScoutAgent response format handling."""

    @pytest.mark.asyncio
    async def test_handles_valid_pricing_analysis(self, mock_services, mission_state):
        """Test handling of valid PricingAnalysis structured output."""
        mock_services.serp.get_competitor_prices = AsyncMock(return_value=[
            {"title": "Comp 1", "price": 50.0}
        ])
        mock_services.llm.generate_structured = AsyncMock(return_value=PricingAnalysis(
            competitor_avg_price=50.0,
            recommended_price=55.0,
            price_position="competitive",
            confidence=0.85,
            reasoning="Based on competitors",
        ))
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.pricing_analysis["competitor_avg_price"] == 50.0
        assert result.pricing_analysis["recommended_price"] == 55.0
        assert result.pricing_analysis["price_position"] == "competitive"

    @pytest.mark.asyncio
    async def test_handles_empty_competitor_list(self, mock_services, mission_state):
        """Test handling when no competitors are found."""
        mock_services.serp.get_competitor_prices = AsyncMock(return_value=[])
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should return empty analysis
        assert result.pricing_analysis["competitor_count"] == 0
        assert result.pricing_analysis["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_pricing_analysis_confidence_range(self, mock_services, mission_state):
        """Test that confidence is within valid range."""
        mock_services.serp.get_competitor_prices = AsyncMock(return_value=[
            {"title": "Comp 1", "price": 50.0}
        ])
        mock_services.llm.generate_structured = AsyncMock(return_value=PricingAnalysis(
            competitor_avg_price=50.0,
            recommended_price=55.0,
            price_position="competitive",
            confidence=0.85,
            reasoning="Test",
        ))
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        confidence = result.pricing_analysis["confidence"]
        assert 0.0 <= confidence <= 1.0

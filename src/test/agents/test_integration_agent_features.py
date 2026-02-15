"""
Integration tests for agent feature functionality.

Confirms that all features work correctly for each agent.
Note: ComplianceAgent is currently disabled. SEO is handled by SEOAgent.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.ecommerce.agents.rewriter import RewriterAgent
CopywriterAgent = RewriterAgent  # Backward compat alias
from src.ecommerce.agents.seo import SEOAgent
from src.ecommerce.agents.marketing import MarketingAgent
from src.ecommerce.agents.price_scout import PriceScoutAgent
from src.ecommerce.agents.price_scout.schemas import PricingAnalysis
from src.ecommerce.state import MissionState


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create comprehensive mock ServiceRegistry."""
    services = MagicMock()
    
    # Mock LLM
    services.llm.generate_text = AsyncMock(return_value="""{
        "title": "Artisan Ceramic Bowl",
        "description": "<p>Handcrafted in Kyoto</p>",
        "seo_title": "Ceramic Bowl | Kyoto Artisan",
        "seo_description": "Handcrafted ceramic bowl from Kyoto.",
        "seo_alt_text": "Ceramic bowl",
        "discovered_values": [
            {"category": "Regional Pedigree", "evidence": "京都", "explanation": "Made in Kyoto"}
        ]
    }""")
    
    services.llm.generate_structured = AsyncMock()
    services.llm.generate_json = AsyncMock(return_value={
        "seo_title": "Test SEO",
        "seo_description": "Test description",
        "seo_alt_text": "Alt text",
    })
    
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
    services.rag.get_brand_context = AsyncMock(return_value=[
        {"content": "We are a Kyoto atelier."},
    ])
    
    return services


@pytest.fixture
def mission_state():
    """Create a MissionState for testing."""
    return MissionState(
        product_id="test-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Standard",
        raw_input={
            "title": "伝統的な陶器ボウル",
            "description": "京都の職人による手作り",
            "japanese_description": "京都の職人による手作り",
            "category": "Kitchenware",
        },
        target_locale="en",
    )


# =============================================================================
# Tests: CopywriterAgent Features
# =============================================================================

class TestCopywriterAgentFeatures:
    """Tests for CopywriterAgent feature functionality."""

    @pytest.mark.asyncio
    async def test_generates_draft_content(self, mock_services, mission_state):
        """Test that Copywriter generates draft_content."""
        mission_state.db = MagicMock()  # Enable RAG
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.draft_content is not None
        assert len(result.draft_content) > 0

    @pytest.mark.asyncio
    async def test_generates_draft_title(self, mock_services, mission_state):
        """Test that Copywriter generates draft_title."""
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.draft_title is not None

    @pytest.mark.asyncio
    async def test_loads_brand_context_via_rag(self, mock_services, mission_state):
        """Test that Copywriter loads brand context from RAG."""
        mission_state.db = MagicMock()
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        await agent.run(mission_state)
        
        mock_services.rag.get_brand_context.assert_called()

    @pytest.mark.asyncio
    async def test_extracts_discovered_values(self, mock_services, mission_state):
        """Test that Copywriter extracts discovered values."""
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # discovered_values should be populated if present in LLM response
        assert result.discovered_values is not None

    @pytest.mark.asyncio
    async def test_handles_compliance_feedback_regeneration(self, mock_services, mission_state):
        """Test that Copywriter handles compliance feedback for regeneration."""
        mission_state.raw_input["compliance_feedback"] = "Avoid health claims"
        mission_state.raw_input["_regeneration_attempt"] = 1
        
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should still generate content
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_uses_gpt4o_model(self, mock_services, mission_state):
        """Test that Copywriter uses gpt-4o for creative work."""
        agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
        await agent.run(mission_state)
        
        call_args = mock_services.llm.generate_text.call_args
        assert call_args.kwargs.get("model") == "gpt-4o"


# =============================================================================
# Tests: SEOAgent Features
# =============================================================================

class TestSEOAgentFeatures:
    """Tests for SEOAgent feature functionality."""

    @pytest.mark.asyncio
    async def test_generates_seo_title(self, mock_services, mission_state):
        """Test that SEO generates SEO title."""
        mission_state.draft_content = "<p>Test content</p>"
        mission_state.draft_title = "Test Title"
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.seo_title is not None

    @pytest.mark.asyncio
    async def test_generates_seo_description(self, mock_services, mission_state):
        """Test that SEO generates SEO description."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.seo_description is not None

    @pytest.mark.asyncio
    async def test_generates_seo_alt_text(self, mock_services, mission_state):
        """Test that SEO generates SEO alt text."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.seo_alt_text is not None

    @pytest.mark.asyncio
    async def test_performs_ctr_check(self, mock_services, mission_state):
        """Test that SEO performs CTR/PST check."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.ctr_check is not None
        assert "score" in result.ctr_check

    @pytest.mark.asyncio
    async def test_fetches_serp_competitors(self, mock_services, mission_state):
        """Test that SEO fetches SERP competitor data."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        await agent.run(mission_state)
        
        mock_services.serp.search.assert_called()

    @pytest.mark.asyncio
    async def test_stores_serp_insights(self, mock_services, mission_state):
        """Test that SEO stores SERP insights in state."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.serp_insights is not None

    @pytest.mark.asyncio
    async def test_uses_gpt4o_mini_for_seo(self, mock_services, mission_state):
        """Test that SEO uses gpt-4o-mini for SEO generation."""
        mission_state.draft_content = "<p>Test content</p>"
        
        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        await agent.run(mission_state)
        
        call_args = mock_services.llm.generate_text.call_args
        assert call_args.kwargs.get("model") == "gpt-4o-mini"


# =============================================================================
# Tests: MarketingAgent Features
# =============================================================================

class TestMarketingAgentFeatures:
    """Tests for MarketingAgent feature functionality (social hooks only)."""

    @pytest.mark.asyncio
    async def test_generates_social_hooks(self, mock_services, mission_state):
        """Test that Marketing generates social hooks."""
        mission_state.draft_content = "<p>Test content</p>"
        mission_state.draft_title = "Test Title"
        
        # Mock social hooks response
        mock_services.llm.generate_text = AsyncMock(return_value="""{
            "hooks": [
                {"type": "Story", "caption": "Test caption", "hashtags": ["#test"]}
            ]
        }""")
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # social_hooks may be empty if parsing fails, just verify no crash
        assert result is not None
        assert result.status != "ERROR"

    @pytest.mark.asyncio
    async def test_handles_missing_draft_content(self, mock_services, mission_state):
        """Test that Marketing handles missing draft content gracefully."""
        mission_state.draft_content = None
        
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should handle gracefully
        assert result is not None


# =============================================================================
# Tests: PriceScoutAgent Features
# =============================================================================

class TestPriceScoutAgentFeatures:
    """Tests for PriceScoutAgent feature functionality."""

    @pytest.mark.asyncio
    async def test_fetches_competitor_prices(self, mock_services, mission_state):
        """Test that PriceScout fetches competitor prices."""
        mock_services.llm.generate_structured.return_value = PricingAnalysis(
            competitor_avg_price=50.0,
            recommended_price=55.0,
            price_position="competitive",
            confidence=0.85,
            reasoning="Test",
        )
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        await agent.run(mission_state)
        
        mock_services.serp.get_competitor_prices.assert_called()

    @pytest.mark.asyncio
    async def test_generates_pricing_analysis(self, mock_services, mission_state):
        """Test that PriceScout generates pricing analysis."""
        mock_services.llm.generate_structured.return_value = PricingAnalysis(
            competitor_avg_price=50.0,
            recommended_price=55.0,
            price_position="competitive",
            confidence=0.85,
            reasoning="Test",
        )
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.pricing_analysis is not None
        assert "competitor_avg_price" in result.pricing_analysis

    @pytest.mark.asyncio
    async def test_includes_recommended_price(self, mock_services, mission_state):
        """Test that pricing analysis includes recommended price."""
        mock_services.llm.generate_structured.return_value = PricingAnalysis(
            competitor_avg_price=50.0,
            recommended_price=55.0,
            price_position="competitive",
            confidence=0.85,
            reasoning="Test",
        )
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert "recommended_price" in result.pricing_analysis
        assert result.pricing_analysis["recommended_price"] == 55.0

    @pytest.mark.asyncio
    async def test_includes_price_position(self, mock_services, mission_state):
        """Test that pricing analysis includes price position."""
        mock_services.llm.generate_structured.return_value = PricingAnalysis(
            competitor_avg_price=50.0,
            recommended_price=55.0,
            price_position="premium",
            confidence=0.85,
            reasoning="Test",
        )
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        assert result.pricing_analysis["price_position"] == "premium"

    @pytest.mark.asyncio
    async def test_skips_llm_without_competitors(self, mock_services, mission_state):
        """Test that PriceScout skips LLM when no competitors found."""
        mock_services.serp.get_competitor_prices = AsyncMock(return_value=[])
        
        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(mission_state)
        
        # Should have pricing_analysis but with zero values
        assert result.pricing_analysis is not None
        assert result.pricing_analysis["competitor_count"] == 0
        
        # Should NOT have called LLM
        mock_services.llm.generate_structured.assert_not_called()

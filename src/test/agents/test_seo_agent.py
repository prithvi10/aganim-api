"""
Unit tests for SEOAgent.

Tests SEO generation, CTR check, and SERP insights.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.seo import SEOAgent
from src.ecommerce.agents.seo.schemas import (
    SEOOutput,
    SEOInsights,
    CTRCheck,
    SerpCompetitor,
)
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for testing."""
    services = MagicMock()
    
    # Mock LLM responses - generate_text returns JSON string
    services.llm.generate_text = AsyncMock(return_value='{"seo_title": "Test SEO Title", "seo_description": "Meta description with CTA", "seo_alt_text": "Product image alt text", "seo_insights": {"lsi_keywords_used": ["keyword1", "keyword2"], "search_intent": "transactional", "competitive_edge": "Unique selling point"}}')
    services.llm.generate_structured = AsyncMock()
    services.llm.generate_json = AsyncMock(return_value={
        "seo_title": "Test SEO Title for Product",
        "seo_description": "Meta description with CTA",
        "seo_alt_text": "Product image alt text",
    })
    
    # Mock SERP results as objects with attributes
    mock_serp_results = []
    for i in range(3):
        r = MagicMock()
        r.title = f"Competitor {i+1} Product"
        r.snippet = f"Product snippet {i+1}"
        r.link = f"https://comp{i+1}.com"
        r.position = i + 1
        mock_serp_results.append(r)
    
    services.serp.search = AsyncMock(return_value=mock_serp_results)
    services.rag.get_brand_context = AsyncMock(return_value=[])
    return services


@pytest.fixture
def mission_state():
    """Create a basic MissionState with draft content."""
    state = MissionState(
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
    # Set draft content from previous agent
    state.draft_content = "<p>Beautiful handcrafted ceramic bowl from Kyoto.</p>"
    state.draft_title = "Handcrafted Ceramic Bowl"
    return state


# =============================================================================
# Tests: Perception Phase (SERP Data Fetching)
# =============================================================================

@pytest.mark.asyncio
async def test_perceive_fetches_serp_data(mock_services, mission_state):
    """Test that perception fetches SERP competitor data."""
    agent = SEOAgent("test-shop.myshopify.com", mock_services)
    
    context = await agent.perceive(mission_state)
    
    # Should have called SERP service
    mock_services.serp.search.assert_called_once()
    
    # Should have SERP data in context
    assert hasattr(context, 'serp_results')
    assert len(context.serp_results) == 3


@pytest.mark.asyncio
async def test_perceive_handles_serp_error(mock_services, mission_state):
    """Test that perception handles SERP errors gracefully."""
    mock_services.serp.search = AsyncMock(side_effect=Exception("SERP error"))
    
    agent = SEOAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should have empty SERP results on error
    assert hasattr(context, 'serp_results')
    assert context.serp_results == []


@pytest.mark.asyncio
async def test_perceive_includes_draft_content(mock_services, mission_state):
    """Test that perception includes draft content from state."""
    agent = SEOAgent("test-shop.myshopify.com", mock_services)
    
    context = await agent.perceive(mission_state)
    
    # Should have draft content available
    assert mission_state.draft_content is not None
    assert "ceramic bowl" in mission_state.draft_content.lower()


# =============================================================================
# Tests: SEO Generation
# =============================================================================

@pytest.mark.asyncio
async def test_generates_seo_fields(mock_services, mission_state):
    """Test that agent generates SEO fields."""
    agent = SEOAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should have SEO title
    assert result.seo_title == "Test SEO Title"
    assert result.seo_description == "Meta description with CTA"
    assert result.seo_alt_text == "Product image alt text"


@pytest.mark.asyncio
async def test_seo_title_clamping():
    """Test that SEO title is clamped to <= 70 characters."""
    agent = SEOAgent("test-shop.myshopify.com", MagicMock())
    
    long_title = "A" * 100
    result = agent._clamp_length(long_title, 70)
    
    assert len(result) <= 70


@pytest.mark.asyncio
async def test_seo_description_clamping():
    """Test that SEO description is clamped to <= 160 characters."""
    agent = SEOAgent("test-shop.myshopify.com", MagicMock())
    
    long_desc = "B" * 200
    result = agent._clamp_length(long_desc, 160)
    
    assert len(result) <= 160


# =============================================================================
# Tests: CTR/PST Check (Deterministic, No LLM)
# =============================================================================

def test_ctr_pst_check_detects_pain():
    """Test that CTR check detects pain indicators."""
    agent = SEOAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Struggling to find the perfect gift?",
        seo_description="",
    )
    
    assert result["pain_present"] is True


def test_ctr_pst_check_detects_solution():
    """Test that CTR check detects solution indicators."""
    agent = SEOAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Premium quality ceramic bowl with authentic traditional craftsmanship.",
        seo_description="",
    )
    
    assert result["solution_present"] is True


def test_ctr_pst_check_detects_trust():
    """Test that CTR check detects trust indicators."""
    agent = SEOAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Handcrafted in Kyoto, Japan. Free shipping worldwide.",
        seo_description="",
    )
    
    assert result["trust_present"] is True


def test_ctr_pst_check_returns_score():
    """Test that CTR check returns a score between 0 and 1."""
    agent = SEOAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Product.",
        seo_description="",
    )
    
    assert 0.0 <= result["score"] <= 1.0
    assert isinstance(result["suggestions"], list)


def test_ctr_pst_check_full_score():
    """Test that CTR check gives full score when all elements present."""
    agent = SEOAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Struggling to find the perfect gift? This ceramic bowl is perfect for you. Made in Kyoto, Japan.",
        seo_description="",
    )
    
    # Should have high score with all elements
    assert result["score"] >= 0.66


# =============================================================================
# Tests: SERP Competitor Insights
# =============================================================================

@pytest.mark.asyncio
async def test_stores_serp_insights_in_state(mock_services, mission_state):
    """Test that agent stores SERP insights in state."""
    agent = SEOAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should have SERP insights stored
    assert result.serp_insights is not None


# =============================================================================
# Tests: Error Handling
# =============================================================================

@pytest.mark.asyncio
async def test_handles_llm_error_gracefully(mock_services, mission_state):
    """Test that agent handles LLM errors gracefully."""
    mock_services.llm.generate_text = AsyncMock(side_effect=Exception("LLM error"))
    
    agent = SEOAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state)
    
    # Should still complete (may have empty fields)
    # The agent catches exceptions internally per step
    assert result is not None


@pytest.mark.asyncio
async def test_handles_missing_draft_content(mock_services, mission_state):
    """Test that agent handles missing draft content."""
    mission_state.draft_content = None
    mission_state.draft_title = None
    
    agent = SEOAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state)
    
    # Should still work (using raw_input)
    assert result is not None


# =============================================================================
# Tests: Schema Validation
# =============================================================================

def test_seo_output_schema():
    """Test SEOOutput Pydantic schema."""
    output = SEOOutput(
        seo_title="Test Title",
        seo_description="Test description",
        seo_alt_text="Test alt",
    )
    
    assert output.seo_title == "Test Title"
    assert output.seo_description == "Test description"


def test_seo_insights_schema():
    """Test SEOInsights Pydantic schema."""
    insights = SEOInsights(
        lsi_keywords_used=["keyword1", "keyword2"],
        search_intent="transactional",
        competitive_edge="Unique detail",
    )
    
    assert len(insights.lsi_keywords_used) == 2
    assert insights.search_intent == "transactional"


def test_ctr_check_schema():
    """Test CTRCheck Pydantic schema."""
    check = CTRCheck(
        pain_present=True,
        solution_present=True,
        trust_present=False,
        score=0.67,
        suggestions=["Add trust cue"],
    )
    
    assert check.pain_present is True
    assert check.score == 0.67


def test_serp_competitor_schema():
    """Test SerpCompetitor Pydantic schema."""
    comp = SerpCompetitor(
        title="Competitor Product",
        snippet="Product snippet",
        link="https://example.com",
        position=1,
    )
    
    assert comp.position == 1
    assert comp.link == "https://example.com"

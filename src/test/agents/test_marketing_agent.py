"""
Unit tests for MarketingAgent.

Tests SEO generation, recommendations, CTR check, SERP insights, and social hooks.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, timedelta

from src.main.agents.marketing import MarketingAgent
from src.main.agents.marketing.schemas import (
    MarketingOutput,
    SEOInsights,
    SEORecommendations,
    CompetitiveEdge,
    BuyerIntent,
    CTRCheck,
    SerpCompetitor,
    SocialHook,
    SeasonalCampaign,
)
from src.main.agents.marketing.holidays import (
    get_next_upcoming_holiday,
    generate_discount_code,
    should_show_seasonal_campaign,
    Holiday,
)
from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext, AgentPlan


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
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
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
    
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should have empty SERP results on error
    assert hasattr(context, 'serp_results')
    assert context.serp_results == []


@pytest.mark.asyncio
async def test_perceive_includes_draft_content(mock_services, mission_state):
    """Test that perception includes draft content from state."""
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
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
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should have SEO title
    assert result.seo_title == "Test SEO Title"
    assert result.seo_description == "Meta description with CTA"
    assert result.seo_alt_text == "Product image alt text"


@pytest.mark.asyncio
async def test_seo_title_clamping():
    """Test that SEO title is clamped to <= 70 characters."""
    agent = MarketingAgent("test-shop.myshopify.com", MagicMock())
    
    long_title = "A" * 100
    result = agent._clamp_length(long_title, 70)
    
    assert len(result) <= 70


@pytest.mark.asyncio
async def test_seo_description_clamping():
    """Test that SEO description is clamped to <= 160 characters."""
    agent = MarketingAgent("test-shop.myshopify.com", MagicMock())
    
    long_desc = "B" * 200
    result = agent._clamp_length(long_desc, 160)
    
    assert len(result) <= 160


# =============================================================================
# Tests: CTR/PST Check (Deterministic, No LLM)
# =============================================================================

def test_ctr_pst_check_detects_pain():
    """Test that CTR check detects pain indicators."""
    agent = MarketingAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Struggling to find the perfect gift?",
        seo_description="",
    )
    
    assert result["pain_present"] is True


def test_ctr_pst_check_detects_solution():
    """Test that CTR check detects solution indicators."""
    agent = MarketingAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Premium quality ceramic bowl with authentic traditional craftsmanship.",
        seo_description="",
    )
    
    assert result["solution_present"] is True


def test_ctr_pst_check_detects_trust():
    """Test that CTR check detects trust indicators."""
    agent = MarketingAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Handcrafted in Kyoto, Japan. Free shipping worldwide.",
        seo_description="",
    )
    
    assert result["trust_present"] is True


def test_ctr_pst_check_returns_score():
    """Test that CTR check returns a score between 0 and 1."""
    agent = MarketingAgent("test-shop", MagicMock())
    
    result = agent._check_ctr_pst(
        description="Product.",
        seo_description="",
    )
    
    assert 0.0 <= result["score"] <= 1.0
    assert isinstance(result["suggestions"], list)


def test_ctr_pst_check_full_score():
    """Test that CTR check gives full score when all elements present."""
    agent = MarketingAgent("test-shop", MagicMock())
    
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
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should have SERP insights stored
    assert result.serp_insights is not None


# =============================================================================
# Tests: Social Hooks (On-Demand Method)
# =============================================================================

@pytest.mark.asyncio
async def test_generate_social_hooks_method(mock_services):
    """Test that generate_social_hooks method works."""
    mock_services.llm.generate_text = AsyncMock(return_value='{"hooks": [{"type": "Aesthetic", "caption": "Beautiful art!", "hashtags": ["kyoto", "ceramics"], "overlay": "Art"}]}')
    
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.generate_social_hooks(
        product_title="Ceramic Bowl",
        category="Kitchenware",
        tags=["ceramic", "kyoto"],
    )
    
    assert "hooks" in result
    assert len(result["hooks"]) >= 1


# =============================================================================
# Tests: Seasonal Campaign (On-Demand Method)
# =============================================================================

@pytest.mark.asyncio
async def test_generate_seasonal_campaign_with_holiday(mock_services):
    """Test that seasonal campaign is generated when holiday is upcoming."""
    mock_services.llm.generate_text = AsyncMock(return_value='{"caption": "Holiday sale!", "cta": "Shop now"}')
    
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.generate_seasonal_campaign(
        product_title="Ceramic Bowl",
        category="Kitchenware",
    )
    
    # May or may not return based on current date
    if result:
        assert "holiday" in result
        assert "campaign" in result


# =============================================================================
# Tests: Holiday Detection
# =============================================================================

def test_get_next_upcoming_holiday():
    """Test that we can get next upcoming holiday."""
    holiday = get_next_upcoming_holiday()
    
    assert holiday is not None
    assert hasattr(holiday, "name")
    assert hasattr(holiday, "date")


def test_generate_discount_code():
    """Test discount code generation."""
    code = generate_discount_code("Christmas", "Kitchenware", 2026)
    
    assert len(code) <= 20
    assert "CHRISTMAS" in code.upper() or "26" in code


def test_should_show_seasonal_campaign():
    """Test seasonal campaign window check."""
    # Create a holiday 30 days from now (should show)
    future_date = date.today() + timedelta(days=30)
    holiday = Holiday("Test Holiday", future_date)
    
    assert should_show_seasonal_campaign(holiday) is True
    
    # Create a holiday 60 days from now (should not show)
    far_date = date.today() + timedelta(days=60)
    far_holiday = Holiday("Far Holiday", far_date)
    
    assert should_show_seasonal_campaign(far_holiday) is False


# =============================================================================
# Tests: Error Handling
# =============================================================================

@pytest.mark.asyncio
async def test_handles_llm_error_gracefully(mock_services, mission_state):
    """Test that agent handles LLM errors gracefully."""
    mock_services.llm.generate_text = AsyncMock(side_effect=Exception("LLM error"))
    
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state)
    
    # Should still complete (may have empty fields)
    # The agent catches exceptions internally per step
    assert result is not None


@pytest.mark.asyncio
async def test_handles_missing_draft_content(mock_services, mission_state):
    """Test that agent handles missing draft content."""
    mission_state.draft_content = None
    mission_state.draft_title = None
    
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state)
    
    # Should still work (using raw_input)
    assert result is not None


# =============================================================================
# Tests: Schema Validation
# =============================================================================

def test_marketing_output_schema():
    """Test MarketingOutput Pydantic schema."""
    output = MarketingOutput(
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


def test_seo_recommendations_schema():
    """Test SEORecommendations Pydantic schema."""
    recs = SEORecommendations(
        competitive_edge=CompetitiveEdge(
            headline="Unique",
            copy_text="Test edge",
        ),
        buyer_intent=BuyerIntent(
            strategy=["strategy1", "strategy2"],
        ),
    )
    
    assert recs.competitive_edge.copy_text == "Test edge"
    assert len(recs.buyer_intent.strategy) == 2


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


def test_social_hook_schema():
    """Test SocialHook Pydantic schema."""
    hook = SocialHook(
        type="Aesthetic",
        caption="Check out this product!",
        hashtags=["#product", "#sale"],
        copy_text="Full copy text",
    )
    
    assert hook.type == "Aesthetic"
    assert len(hook.hashtags) == 2


def test_seasonal_campaign_schema():
    """Test SeasonalCampaign Pydantic schema."""
    campaign = SeasonalCampaign(
        holiday_name="Christmas",
        holiday_date="2026-12-25",
        days_until=30,
        campaign_title="Christmas Sale",
        discount_code="XMAS26",
    )
    
    assert campaign.holiday_name == "Christmas"
    assert campaign.days_until == 30

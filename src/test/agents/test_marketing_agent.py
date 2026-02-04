"""
Unit tests for MarketingAgent.

Tests social hooks and seasonal campaign generation (SEO moved to SEOAgent).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, timedelta

from src.main.agents.marketing import MarketingAgent
from src.main.agents.marketing.schemas import (
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
    
    # Mock LLM responses for social hooks
    services.llm.generate_text = AsyncMock(return_value='{"hooks": [{"type": "Aesthetic", "caption": "Beautiful art!", "hashtags": ["kyoto", "ceramics"], "overlay": "Art"}]}')
    services.llm.generate_structured = AsyncMock()
    services.llm.generate_json = AsyncMock(return_value={
        "hooks": [
            {"type": "Aesthetic", "caption": "Beautiful ceramic bowl!", "hashtags": ["kyoto", "ceramics"], "copy_text": "Check out this beauty!"}
        ]
    })
    
    # Mock SERP (not used by Marketing anymore, but kept for interface)
    services.serp.search = AsyncMock(return_value=[])
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
# Tests: Social Hooks Generation
# =============================================================================

@pytest.mark.asyncio
async def test_generate_social_hooks_method(mock_services):
    """Test that generate_social_hooks method works."""
    mock_services.llm.generate_text = AsyncMock(return_value='{"hooks": [{"type": "Aesthetic", "caption": "Beautiful art!", "hashtags": ["kyoto", "ceramics"], "overlay": "Art", "copy_text": "Check out this!"}]}')
    
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.generate_social_hooks(
        product_title="Ceramic Bowl",
        category="Kitchenware",
        tags=["ceramic", "kyoto"],
    )
    
    assert "hooks" in result
    assert len(result["hooks"]) >= 1


@pytest.mark.asyncio
async def test_run_generates_social_hooks(mock_services, mission_state):
    """Test that running the agent generates social hooks."""
    mock_services.llm.generate_text = AsyncMock(return_value='{"hooks": [{"type": "Story", "caption": "Behind every bowl...", "hashtags": ["artisan"], "copy_text": "A story of tradition"}]}')
    
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Social hooks should be generated
    assert result.social_hooks is not None


@pytest.mark.asyncio  
async def test_social_hooks_have_required_fields(mock_services, mission_state):
    """Test that social hooks have all required fields."""
    hook_data = {
        "hooks": [{
            "type": "Aesthetic",
            "caption": "Beautiful ceramic art from Kyoto",
            "hashtags": ["kyoto", "ceramic", "artisan"],
            "copy_text": "Discover the beauty of Kyoto ceramics"
        }]
    }
    mock_services.llm.generate_text = AsyncMock(return_value=str(hook_data).replace("'", '"'))
    
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    if result.social_hooks:
        for hook in result.social_hooks:
            assert "type" in hook or hook.get("type") is not None
            assert "caption" in hook or hook.get("caption") is not None


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


# =============================================================================
# Tests: Agent Properties
# =============================================================================

def test_agent_role_name(mock_services):
    """Test that agent has correct role name."""
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    assert agent.role_name == "Marketing"


def test_agent_default_tool(mock_services):
    """Test that agent has correct default tool."""
    agent = MarketingAgent("test-shop.myshopify.com", mock_services)
    
    assert agent.default_tool == "llm.generate_text"

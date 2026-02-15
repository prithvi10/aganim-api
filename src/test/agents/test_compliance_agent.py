"""
Unit tests for ComplianceAgent.

Tests regex pre-filtering, LLM-as-judge analysis, and flag handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.ecommerce.agents.compliance import ComplianceAgent
from src.ecommerce.agents.compliance.schemas import ComplianceCheck
from src.ecommerce.agents.compliance.patterns import (
    FDA_PATTERNS,
    FTC_PATTERNS,
    SUPPLEMENT_PATTERNS,
    get_pattern_category,
)
from src.ecommerce.state import MissionState
from src.agentic_core.agents.context import AgentContext


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for testing."""
    services = MagicMock()
    
    # Mock LLM service - returns ComplianceCheck
    services.llm.generate_structured = AsyncMock(return_value=ComplianceCheck(
        has_violations=False,
        flags=[],
        severity="none",
        suggestions=[],
    ))
    
    services.llm.generate_text = AsyncMock(return_value="{}")
    services.rag.get_brand_context = AsyncMock(return_value=[])
    services.serp.search = AsyncMock(return_value=[])
    
    return services


@pytest.fixture
def mission_state():
    """Create a basic MissionState for testing."""
    return MissionState(
        product_id="test-product-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Standard",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "description": "Made in Kyoto using traditional techniques.",
            "category": "Kitchenware",
        },
        target_locale="en",
        draft_content="<p>Beautiful handcrafted ceramic bowl from Kyoto.</p>",
    )


@pytest.fixture
def mission_state_with_violations(mission_state):
    """MissionState with content containing compliance violations."""
    mission_state.draft_content = """
    <p>This miracle cure will treat all your ailments!</p>
    <p>FDA approved and clinically proven to work.</p>
    <p>100% effective with no side effects.</p>
    """
    return mission_state


# =============================================================================
# Tests: Regex Pre-filtering (Perception Phase)
# =============================================================================

@pytest.mark.asyncio
async def test_perceive_detects_fda_patterns(mock_services, mission_state_with_violations):
    """Test that perception detects FDA violation patterns."""
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    context = await agent.perceive(mission_state_with_violations)
    
    # Should have regex flags
    regex_flags = context.external_data.get("regex_flags", [])
    assert len(regex_flags) > 0
    
    # Should detect "cure", "treat", etc.
    flag_text = " ".join(regex_flags).lower()
    assert any(word in flag_text for word in ["fda", "cure", "treat", "miracle"])


@pytest.mark.asyncio
async def test_perceive_detects_ftc_patterns(mock_services, mission_state):
    """Test that perception detects FTC violation patterns."""
    mission_state.draft_content = "This is the best in the world! 100% risk-free!"
    
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    regex_flags = context.external_data.get("regex_flags", [])
    assert len(regex_flags) > 0
    
    flag_text = " ".join(regex_flags).lower()
    assert any(word in flag_text for word in ["ftc", "risk-free", "best"])


@pytest.mark.asyncio
async def test_perceive_no_flags_for_clean_content(mock_services, mission_state):
    """Test that perception returns no flags for clean content."""
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    context = await agent.perceive(mission_state)
    
    regex_flags = context.external_data.get("regex_flags", [])
    assert len(regex_flags) == 0


@pytest.mark.asyncio
async def test_perceive_handles_empty_content(mock_services, mission_state):
    """Test that perception handles empty content."""
    mission_state.draft_content = ""
    
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    assert context.external_data.get("regex_check_done") is True
    assert context.external_data.get("regex_flags", []) == []


# =============================================================================
# Tests: LLM-as-Judge (Action Phase)
# =============================================================================

@pytest.mark.asyncio
async def test_act_uses_llm_judge(mock_services, mission_state):
    """Test that action uses LLM as judge."""
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state)
    
    # Should have called generate_structured
    mock_services.llm.generate_structured.assert_called_once()
    
    # Should use ComplianceCheck schema
    call_args = mock_services.llm.generate_structured.call_args
    assert call_args.kwargs["response_format"] == ComplianceCheck


@pytest.mark.asyncio
async def test_act_combines_regex_and_llm_flags(mock_services, mission_state_with_violations):
    """Test that action combines regex and LLM flags."""
    # Mock LLM to return additional flags
    mock_services.llm.generate_structured = AsyncMock(return_value=ComplianceCheck(
        has_violations=True,
        flags=["Unverified health claim"],
        severity="high",
        suggestions=["Remove health claims"],
    ))
    
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state_with_violations)
    
    # Should have both regex and LLM flags
    assert len(result.compliance_flags) > 0
    # Should include LLM flag
    assert any("Unverified" in f for f in result.compliance_flags) or \
           any("FDA" in f or "FTC" in f for f in result.compliance_flags)


@pytest.mark.asyncio
async def test_act_deduplicates_flags(mock_services, mission_state):
    """Test that action deduplicates flags."""
    mission_state.draft_content = "This cure will cure you!"  # "cure" appears twice
    
    # Mock LLM to return same flag
    mock_services.llm.generate_structured = AsyncMock(return_value=ComplianceCheck(
        has_violations=True,
        flags=["Found 'cure' - potential FDA violation"],
        severity="medium",
        suggestions=[],
    ))
    
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should have deduplicated flags (no exact duplicates)
    unique_flags = set(result.compliance_flags)
    assert len(unique_flags) == len(result.compliance_flags)


@pytest.mark.asyncio
async def test_act_skips_llm_for_empty_content(mock_services, mission_state):
    """Test that action skips LLM call for empty content."""
    mission_state.draft_content = ""
    
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Should NOT have called LLM (for empty content it skips)
    mock_services.llm.generate_structured.assert_not_called()
    
    # Should have empty flags
    assert result.compliance_flags == []


@pytest.mark.asyncio
async def test_act_sets_compliance_review_status(mock_services, mission_state_with_violations):
    """Test that action sets status to COMPLIANCE_REVIEW when issues found."""
    mock_services.llm.generate_structured = AsyncMock(return_value=ComplianceCheck(
        has_violations=True,
        flags=["Issue found"],
        severity="medium",
        suggestions=[],
    ))
    
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state_with_violations)
    
    assert result.status == "COMPLIANCE_REVIEW"


@pytest.mark.asyncio
async def test_act_passes_clean_content(mock_services, mission_state):
    """Test that action does not flag clean content."""
    mock_services.llm.generate_structured = AsyncMock(return_value=ComplianceCheck(
        has_violations=False,
        flags=[],
        severity="none",
        suggestions=[],
    ))
    
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    assert len(result.compliance_flags) == 0
    # Status should not be COMPLIANCE_REVIEW
    assert result.status != "COMPLIANCE_REVIEW"


# =============================================================================
# Tests: Error Handling
# =============================================================================

@pytest.mark.asyncio
async def test_act_falls_back_to_regex_on_llm_error(mock_services, mission_state_with_violations):
    """Test that action falls back to regex-only flags on LLM error."""
    mock_services.llm.generate_structured = AsyncMock(side_effect=Exception("LLM error"))
    
    agent = ComplianceAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state_with_violations)
    
    # Should still have regex flags
    assert len(result.compliance_flags) > 0
    assert result.status == "COMPLIANCE_REVIEW"


# =============================================================================
# Tests: Prompt Building
# =============================================================================

def test_build_check_prompt_includes_content():
    """Test that check prompt includes content."""
    agent = ComplianceAgent("test-shop", MagicMock())
    
    prompt = agent._build_check_prompt(
        content="Test content to check",
        regex_flags=[],
    )
    
    assert "Test content to check" in prompt


def test_build_check_prompt_includes_regex_flags():
    """Test that check prompt includes regex flags."""
    agent = ComplianceAgent("test-shop", MagicMock())
    
    prompt = agent._build_check_prompt(
        content="Test content",
        regex_flags=["Potential FDA violation: found 'cure'"],
    )
    
    assert "FDA violation" in prompt
    assert "cure" in prompt


def test_build_check_prompt_truncates_long_content():
    """Test that check prompt truncates very long content."""
    agent = ComplianceAgent("test-shop", MagicMock())
    
    long_content = "A" * 10000
    prompt = agent._build_check_prompt(
        content=long_content,
        regex_flags=[],
    )
    
    # Should be truncated
    assert len(prompt) < len(long_content)
    assert "..." in prompt


# =============================================================================
# Tests: Pattern Matching
# =============================================================================

def test_fda_patterns_match_cure():
    """Test that FDA patterns match 'cure'."""
    import re
    
    text = "This product cures headaches"
    matches = [p for p in FDA_PATTERNS if re.search(p, text, re.IGNORECASE)]
    
    assert len(matches) > 0


def test_fda_patterns_match_treat():
    """Test that FDA patterns match 'treat'."""
    import re
    
    text = "This product treats skin conditions"
    matches = [p for p in FDA_PATTERNS if re.search(p, text, re.IGNORECASE)]
    
    assert len(matches) > 0


def test_fda_patterns_match_miracle():
    """Test that FDA patterns match 'miracle'."""
    import re
    
    text = "A miracle solution"  # Pattern matches "miracle" or "miraclous"
    matches = [p for p in FDA_PATTERNS if re.search(p, text, re.IGNORECASE)]
    
    assert len(matches) > 0


def test_ftc_patterns_match_risk_free():
    """Test that FTC patterns match 'risk-free'."""
    import re
    
    text = "Completely risk-free purchase"
    matches = [p for p in FTC_PATTERNS if re.search(p, text, re.IGNORECASE)]
    
    assert len(matches) > 0


def test_ftc_patterns_match_no_side_effects():
    """Test that FTC patterns match 'no side effects'."""
    import re
    
    text = "Has absolutely no side effects"
    matches = [p for p in FTC_PATTERNS if re.search(p, text, re.IGNORECASE)]
    
    assert len(matches) > 0


def test_get_pattern_category():
    """Test pattern category lookup."""
    assert get_pattern_category(FDA_PATTERNS[0]) == "FDA"
    assert get_pattern_category(FTC_PATTERNS[0]) == "FTC"
    assert get_pattern_category(SUPPLEMENT_PATTERNS[0]) == "Supplement"
    assert get_pattern_category("unknown pattern") == "Unknown"


# =============================================================================
# Tests: Schema Validation
# =============================================================================

def test_compliance_check_schema():
    """Test ComplianceCheck Pydantic schema."""
    check = ComplianceCheck(
        has_violations=True,
        flags=["FDA violation: found 'cure'"],
        severity="medium",
        suggestions=["Remove health claims"],
    )
    
    assert check.has_violations is True
    assert len(check.flags) == 1
    assert check.severity == "medium"


def test_compliance_check_defaults():
    """Test ComplianceCheck default values."""
    check = ComplianceCheck(
        has_violations=False,
        flags=[],
        severity="none",
        suggestions=[],
    )
    
    assert check.has_violations is False
    assert check.flags == []

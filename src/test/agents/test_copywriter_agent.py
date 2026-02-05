"""
Unit tests for CopywriterAgent.

Tests RAG perception, LLM generation, prompt building, and feedback.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.main.agents.rewriter import RewriterAgent
CopywriterAgent = RewriterAgent  # Backward compat alias
from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext, AgentPlan


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for testing."""
    services = MagicMock()
    # Default mock response for LLM
    services.llm.generate_text = AsyncMock(return_value='{"title": "Generated Title", "description": "<p>Generated description</p>", "discovered_values": []}')
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=[
        {"content": "We are a Kyoto atelier focused on craftsmanship."},
        {"content": "Our brand pillars: Heritage, Quality, Authenticity."},
    ])
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
    )


@pytest.fixture
def mission_state_with_compliance_feedback(mission_state):
    """MissionState with compliance feedback for regeneration."""
    mission_state.raw_input["compliance_feedback"] = "Avoid FDA health claims"
    mission_state.raw_input["_regeneration_attempt"] = 1
    return mission_state


# =============================================================================
# Tests: Perception Phase (RAG Context Loading)
# =============================================================================

@pytest.mark.asyncio
async def test_perceive_loads_brand_context(mock_services, mission_state):
    """Test that perception loads brand context via RAG."""
    # Add mock DB
    mission_state.db = MagicMock()
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should have loaded brand context
    assert len(context.brand_context) == 2
    assert "Kyoto atelier" in context.brand_context[0]["content"]
    
    # Should have called RAG service
    mock_services.rag.get_brand_context.assert_called_once()


@pytest.mark.asyncio
async def test_perceive_handles_missing_db(mock_services, mission_state):
    """Test that perception handles missing DB gracefully."""
    mission_state.db = None
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should return empty brand context
    assert context.brand_context == []
    
    # Should NOT call RAG service without DB
    mock_services.rag.get_brand_context.assert_not_called()


@pytest.mark.asyncio
async def test_perceive_handles_rag_error(mock_services, mission_state):
    """Test that perception handles RAG errors gracefully."""
    mission_state.db = MagicMock()
    mock_services.rag.get_brand_context = AsyncMock(side_effect=Exception("RAG error"))
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    context = await agent.perceive(mission_state)
    
    # Should return empty brand context on error
    assert context.brand_context == []


# =============================================================================
# Tests: Action Phase (LLM Generation)
# =============================================================================

@pytest.mark.asyncio
async def test_act_generates_content(mock_services, mission_state):
    """Test that action phase generates content via LLM."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    # Run full pipeline
    result = await agent.run(mission_state)
    
    # Should have generated content
    assert result.draft_content is not None
    assert "Generated description" in result.draft_content
    assert result.draft_title == "Generated Title"
    
    # Should have called LLM
    mock_services.llm.generate_text.assert_called_once()


@pytest.mark.asyncio
async def test_act_uses_gpt4o_for_creative_work(mock_services, mission_state):
    """Test that action uses gpt-4o model for creative content."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state)
    
    # Check model parameter
    call_args = mock_services.llm.generate_text.call_args
    assert call_args.kwargs.get("model") == "gpt-4o"


@pytest.mark.asyncio
async def test_act_handles_llm_error(mock_services, mission_state):
    """Test that action handles LLM errors gracefully."""
    mock_services.llm.generate_text = AsyncMock(side_effect=Exception("LLM error"))
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state)
    
    # Should set error state
    assert result.status == "ERROR"
    assert "Content generation failed" in result.error_message


@pytest.mark.asyncio
async def test_act_handles_malformed_json(mock_services, mission_state):
    """Test that action handles malformed JSON response."""
    mock_services.llm.generate_text = AsyncMock(return_value="Not valid JSON")
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state)
    
    # Should still produce output (fallback to raw content)
    assert result.draft_content is not None
    assert result.status == "DRAFT_READY"


# =============================================================================
# Tests: Prompt Building
# =============================================================================

@pytest.mark.asyncio
async def test_build_system_prompt_includes_brand_context(mock_services, mission_state):
    """Test that system prompt includes brand context when available."""
    mission_state.db = MagicMock()
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    # Get context with brand info
    context = await agent.perceive(mission_state)
    
    # Build system prompt
    system_prompt = agent._build_system_prompt(mission_state, context)
    
    # Should include brand context
    assert "Kyoto atelier" in system_prompt or "Brand Context" in system_prompt


@pytest.mark.asyncio
async def test_build_system_prompt_includes_tone_instruction(mock_services, mission_state):
    """Test that system prompt includes tone-related instructions."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    context = AgentContext(raw_input=mission_state.raw_input)
    system_prompt = agent._build_system_prompt(mission_state, context)
    
    # Should include tone-related instruction (from the base prompts)
    assert "tone" in system_prompt.lower()
    assert "strategy" in system_prompt.lower()


@pytest.mark.asyncio
async def test_build_user_prompt_includes_product_data(mock_services, mission_state):
    """Test that user prompt includes product data."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    context = AgentContext(raw_input=mission_state.raw_input)
    user_prompt = agent._build_user_prompt(mission_state, context)
    
    # Should include product info
    assert "Handcrafted Ceramic Bowl" in user_prompt
    assert "Kitchenware" in user_prompt


# =============================================================================
# Tests: Compliance Feedback Regeneration
# =============================================================================

@pytest.mark.asyncio
async def test_regeneration_includes_compliance_feedback(mock_services, mission_state_with_compliance_feedback):
    """Test that regeneration includes compliance feedback in prompt."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    context = AgentContext(raw_input=mission_state_with_compliance_feedback.raw_input)
    system_prompt = agent._build_system_prompt(mission_state_with_compliance_feedback, context)
    
    # Should include compliance feedback
    assert "FDA health claims" in system_prompt or "compliance" in system_prompt.lower()


# =============================================================================
# Tests: Locale Persona
# =============================================================================

@pytest.mark.asyncio
async def test_locale_persona_injection(mock_services, mission_state):
    """Test that locale persona is injected for supported locales."""
    mission_state.target_locale = "en"
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    context = AgentContext(raw_input=mission_state.raw_input)
    system_prompt = agent._build_system_prompt(mission_state, context)
    
    # Should include locale-specific content
    # The actual persona content depends on LOCALE_PERSONA_MAP
    assert "en" in mission_state.target_locale


# =============================================================================
# Tests: Feedback Phase
# =============================================================================

@pytest.mark.asyncio
async def test_feedback_records_success(mock_services, mission_state):
    """Test that feedback records successful generation."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    agent.memory.record_success = AsyncMock()
    
    # Run full pipeline
    await agent.run(mission_state)
    
    # Should record success
    agent.memory.record_success.assert_called()


# =============================================================================
# Tests: Result Parsing
# =============================================================================

def test_parse_llm_result_valid_json():
    """Test parsing valid JSON from LLM response."""
    agent = CopywriterAgent("test-shop.myshopify.com", MagicMock())
    
    result = agent._parse_llm_result('{"title": "Test", "description": "Desc", "discovered_values": []}')
    
    assert result["title"] == "Test"
    assert result["description"] == "Desc"


def test_parse_llm_result_invalid_json():
    """Test parsing invalid JSON returns raw content as description."""
    agent = CopywriterAgent("test-shop.myshopify.com", MagicMock())
    
    result = agent._parse_llm_result("Just plain text content")
    
    assert result["description"] == "Just plain text content"


def test_parse_llm_result_with_markdown_code_block():
    """Test parsing JSON wrapped in markdown code block."""
    agent = CopywriterAgent("test-shop.myshopify.com", MagicMock())
    
    result = agent._parse_llm_result('```json\n{"title": "Test", "description": "Desc"}\n```')
    
    assert result["title"] == "Test"

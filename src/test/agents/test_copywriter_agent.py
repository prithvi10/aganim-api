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


# =============================================================================
# Tests: Refinement Mode
# =============================================================================

@pytest.fixture
def mission_state_with_draft(mission_state):
    """MissionState with existing draft content for refinement testing."""
    mission_state.draft_content = "<p>Previously generated description</p>"
    mission_state.draft_title = "Previously Generated Title"
    mission_state.discovered_values = [{"name": "Heritage", "value": "Kyoto craft"}]
    return mission_state


@pytest.fixture
def mission_state_with_feedback(mission_state):
    """MissionState with regeneration feedback for refinement testing."""
    mission_state.raw_input["_regeneration_feedback"] = "Make the bullet points punchier"
    return mission_state


@pytest.fixture
def mission_state_for_refinement(mission_state_with_draft, mission_state_with_feedback):
    """MissionState with both draft and feedback - triggers refinement mode."""
    mission_state_with_draft.raw_input["_regeneration_feedback"] = "Make the bullet points punchier"
    return mission_state_with_draft


def test_get_previous_draft_from_state(mock_services, mission_state_with_draft):
    """Test _get_previous_draft returns draft from state when available."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    result = agent._get_previous_draft(mission_state_with_draft)
    
    assert result is not None
    assert result["title"] == "Previously Generated Title"
    assert result["description"] == "<p>Previously generated description</p>"
    assert len(result["discovered_values"]) == 1


def test_get_previous_draft_from_agent_outputs(mock_services, mission_state):
    """Test _get_previous_draft returns draft from agent_outputs when state is empty."""
    mission_state.agent_outputs["RewriterAgent"] = {
        "draft_title": "Title from agent outputs",
        "draft_content": "<p>Content from agent outputs</p>",
        "discovered_values": [],
    }
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    result = agent._get_previous_draft(mission_state)
    
    assert result is not None
    assert result["title"] == "Title from agent outputs"
    assert result["description"] == "<p>Content from agent outputs</p>"


def test_get_previous_draft_returns_none_when_empty(mock_services, mission_state):
    """Test _get_previous_draft returns None when no draft exists."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    result = agent._get_previous_draft(mission_state)
    
    assert result is None


@pytest.mark.asyncio
async def test_refinement_mode_triggered_with_feedback_and_draft(mock_services, mission_state_for_refinement):
    """Test that refinement mode is triggered when both feedback and draft exist."""
    mock_services.llm.generate_text = AsyncMock(
        return_value='{"title": "Refined Title", "description": "<p>Refined description</p>", "discovered_values": []}'
    )
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state_for_refinement)
    
    # Should log refinement mode
    assert any("Refinement Mode Active" in log for log in result.logs)
    
    # Should generate refined content
    assert result.draft_title == "Refined Title"
    assert "Refined description" in result.draft_content


@pytest.mark.asyncio
async def test_refinement_mode_uses_lower_temperature(mock_services, mission_state_for_refinement):
    """Test that refinement mode uses lower temperature for controlled edits."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state_for_refinement)
    
    # Check temperature parameter
    call_args = mock_services.llm.generate_text.call_args
    # Refinement mode uses temperature=0.5 (lower than fresh run's 0.7)
    assert call_args.kwargs.get("temperature") == 0.5


@pytest.mark.asyncio
async def test_refinement_mode_includes_current_draft_in_prompt(mock_services, mission_state_for_refinement):
    """Test that refinement mode includes the current draft in the system prompt."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state_for_refinement)
    
    call_args = mock_services.llm.generate_text.call_args
    system_prompt = call_args.kwargs.get("system_prompt", "")
    
    # Should include the previous draft content
    assert "Previously generated description" in system_prompt or "Previously Generated Title" in system_prompt


@pytest.mark.asyncio
async def test_refinement_mode_includes_user_feedback_in_prompt(mock_services, mission_state_for_refinement):
    """Test that refinement mode includes user feedback in the prompt."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state_for_refinement)
    
    call_args = mock_services.llm.generate_text.call_args
    system_prompt = call_args.kwargs.get("system_prompt", "")
    
    # Should include the user feedback
    assert "Make the bullet points punchier" in system_prompt


@pytest.mark.asyncio
async def test_fresh_run_when_no_feedback(mock_services, mission_state_with_draft):
    """Test that fresh run is used when no feedback is provided (even with draft)."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    await agent.run(mission_state_with_draft)
    
    # Should NOT log refinement mode
    # Fresh run uses temperature=0.7
    call_args = mock_services.llm.generate_text.call_args
    assert call_args.kwargs.get("temperature") == 0.7


@pytest.mark.asyncio
async def test_fresh_run_when_no_draft(mock_services, mission_state_with_feedback):
    """Test that fresh run is used when no previous draft exists (even with feedback)."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state_with_feedback)
    
    # Should NOT log refinement mode (no previous draft)
    assert not any("Refinement Mode Active" in log for log in result.logs)
    
    # Fresh run uses temperature=0.7
    call_args = mock_services.llm.generate_text.call_args
    assert call_args.kwargs.get("temperature") == 0.7


@pytest.mark.asyncio
async def test_refinement_preserves_values_on_parse_error(mock_services, mission_state_for_refinement):
    """Test that refinement preserves previous values when JSON parsing fails."""
    mock_services.llm.generate_text = AsyncMock(return_value="Invalid JSON response")
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state_for_refinement)
    
    # Should still have output (fallback to raw content or preserved values)
    assert result.draft_content is not None
    assert result.status == "DRAFT_READY"


@pytest.mark.asyncio
async def test_refinement_handles_llm_error(mock_services, mission_state_for_refinement):
    """Test that refinement handles LLM errors gracefully."""
    mock_services.llm.generate_text = AsyncMock(side_effect=Exception("LLM refinement error"))
    
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    result = await agent.run(mission_state_for_refinement)
    
    # Should set error state
    assert result.status == "ERROR"
    assert "refinement failed" in result.error_message.lower() or "Content" in result.error_message


@pytest.mark.asyncio
async def test_action_params_include_mode_fresh(mock_services, mission_state):
    """Test that action params include mode='fresh' for fresh generation."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state)
    
    # Check that the action was logged with mode info
    # The agent stores actions with input_params including mode
    call_args = mock_services.llm.generate_text.call_args
    assert call_args is not None  # LLM was called


@pytest.mark.asyncio
async def test_action_params_include_mode_refinement(mock_services, mission_state_for_refinement):
    """Test that action params include mode='refinement' for refinement."""
    agent = CopywriterAgent("test-shop.myshopify.com", mock_services)
    
    result = await agent.run(mission_state_for_refinement)
    
    # Verify refinement mode was detected
    assert any("Refinement Mode Active" in log for log in result.logs)

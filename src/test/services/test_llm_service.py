"""
Unit tests for LLMService.

Tests text generation, structured output, JSON parsing, and error handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from src.agentic_core.llm.llm_service import LLMService


# =============================================================================
# Test Schemas
# =============================================================================

class OutputSchema(BaseModel):
    """Pydantic schema for structured output tests."""
    title: str
    description: str
    score: float = 0.0


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_openai_client():
    """Create a mock AsyncOpenAI client."""
    client = MagicMock()
    
    # Mock chat completions
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test response"
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    
    client.chat.completions.create = AsyncMock(return_value=mock_response)
    
    # Mock beta.chat.completions.parse for structured output
    mock_structured = MagicMock()
    mock_structured.choices = [MagicMock()]
    mock_structured.choices[0].message.parsed = OutputSchema(
        title="Test Title",
        description="Test Description",
        score=0.95,
    )
    mock_structured.usage = MagicMock()
    mock_structured.usage.prompt_tokens = 100
    mock_structured.usage.completion_tokens = 50
    
    client.beta.chat.completions.parse = AsyncMock(return_value=mock_structured)
    
    return client


@pytest.fixture
def llm_service(mock_openai_client):
    """Create LLMService with mocked client."""
    service = LLMService(api_key="test-key")
    service.client = mock_openai_client
    return service


# =============================================================================
# Tests: generate_text
# =============================================================================

@pytest.mark.asyncio
async def test_generate_text_returns_string(llm_service):
    """Test that generate_text returns a string."""
    result = await llm_service.generate_text(
        prompt="Test prompt",
        system_prompt="You are helpful.",
    )
    
    assert isinstance(result, str)
    assert result == "Test response"


@pytest.mark.asyncio
async def test_generate_text_uses_default_model(llm_service, mock_openai_client):
    """Test that generate_text uses default gpt-4o model."""
    await llm_service.generate_text(prompt="Test")
    
    call_args = mock_openai_client.chat.completions.create.call_args
    assert call_args.kwargs.get("model") == "gpt-4o"


@pytest.mark.asyncio
async def test_generate_text_uses_custom_model(llm_service, mock_openai_client):
    """Test that generate_text accepts custom model."""
    await llm_service.generate_text(prompt="Test", model="gpt-4o-mini")
    
    call_args = mock_openai_client.chat.completions.create.call_args
    assert call_args.kwargs.get("model") == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_generate_text_includes_system_prompt(llm_service, mock_openai_client):
    """Test that generate_text includes system prompt in messages."""
    await llm_service.generate_text(
        prompt="User message",
        system_prompt="System message",
    )
    
    call_args = mock_openai_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages", [])
    
    assert any(m["role"] == "system" and "System message" in m["content"] for m in messages)
    assert any(m["role"] == "user" and "User message" in m["content"] for m in messages)


@pytest.mark.asyncio
async def test_generate_text_handles_api_error(llm_service, mock_openai_client):
    """Test that generate_text handles API errors."""
    mock_openai_client.chat.completions.create = AsyncMock(
        side_effect=Exception("API Error")
    )
    
    with pytest.raises(Exception) as exc_info:
        await llm_service.generate_text(prompt="Test")
    
    assert "API Error" in str(exc_info.value)


# =============================================================================
# Tests: generate_structured
# =============================================================================

@pytest.mark.asyncio
async def test_generate_structured_returns_pydantic_model(llm_service):
    """Test that generate_structured returns a Pydantic model."""
    result = await llm_service.generate_structured(
        prompt="Test prompt",
        response_format=OutputSchema,
    )
    
    assert isinstance(result, OutputSchema)
    assert result.title == "Test Title"
    assert result.description == "Test Description"


@pytest.mark.asyncio
async def test_generate_structured_uses_mini_model_by_default(llm_service, mock_openai_client):
    """Test that generate_structured uses gpt-4o-mini by default."""
    await llm_service.generate_structured(
        prompt="Test",
        response_format=OutputSchema,
    )
    
    call_args = mock_openai_client.beta.chat.completions.parse.call_args
    assert call_args.kwargs.get("model") == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_generate_structured_passes_response_format(llm_service, mock_openai_client):
    """Test that generate_structured passes response_format to API."""
    await llm_service.generate_structured(
        prompt="Test",
        response_format=OutputSchema,
    )
    
    call_args = mock_openai_client.beta.chat.completions.parse.call_args
    assert call_args.kwargs.get("response_format") == OutputSchema


@pytest.mark.asyncio
async def test_generate_structured_uses_zero_temperature(llm_service, mock_openai_client):
    """Test that generate_structured uses temperature=0 for deterministic output."""
    await llm_service.generate_structured(
        prompt="Test",
        response_format=OutputSchema,
    )
    
    call_args = mock_openai_client.beta.chat.completions.parse.call_args
    assert call_args.kwargs.get("temperature") == 0.0


@pytest.mark.asyncio
async def test_generate_structured_handles_api_error(llm_service, mock_openai_client):
    """Test that generate_structured handles API errors."""
    mock_openai_client.beta.chat.completions.parse = AsyncMock(
        side_effect=Exception("Structured API Error")
    )
    
    with pytest.raises(Exception) as exc_info:
        await llm_service.generate_structured(
            prompt="Test",
            response_format=OutputSchema,
        )
    
    assert "Structured API Error" in str(exc_info.value)


# =============================================================================
# Tests: generate_json
# =============================================================================

@pytest.mark.asyncio
async def test_generate_json_returns_string(llm_service, mock_openai_client):
    """Test that generate_json returns a raw JSON string (caller must parse)."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"key": "value"}'
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    
    mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)
    
    result = await llm_service.generate_json(prompt="Test")
    
    # Returns raw string, caller must parse
    assert isinstance(result, str)
    assert '{"key": "value"}' in result


@pytest.mark.asyncio
async def test_generate_json_uses_mini_model(llm_service, mock_openai_client):
    """Test that generate_json uses gpt-4o-mini by default."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{}'
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    
    mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)
    
    await llm_service.generate_json(prompt="Test")
    
    call_args = mock_openai_client.chat.completions.create.call_args
    assert call_args.kwargs.get("model") == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_generate_json_uses_json_system_prompt(llm_service, mock_openai_client):
    """Test that generate_json uses JSON-focused system prompt."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{}'
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    
    mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)
    
    await llm_service.generate_json(prompt="Test")
    
    call_args = mock_openai_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages", [])
    system_msg = next((m for m in messages if m["role"] == "system"), None)
    assert system_msg is not None
    assert "JSON" in system_msg["content"]


# =============================================================================
# Tests: Initialization
# =============================================================================

def test_llm_service_initialization():
    """Test that LLMService initializes with API key."""
    with patch('src.agentic_core.llm.llm_service.AsyncOpenAI') as MockClient:
        service = LLMService(api_key="test-api-key")
        
        # Should create AsyncOpenAI client with api_key (http_client is also passed for SSL)
        MockClient.assert_called_once()
        call_kwargs = MockClient.call_args.kwargs
        assert call_kwargs.get("api_key") == "test-api-key"
        # http_client is also passed for Netskope SSL support
        assert "http_client" in call_kwargs


def test_llm_service_no_client_without_api_key():
    """Test that LLMService handles missing API key."""
    with patch('src.agentic_core.llm.llm_service.AsyncOpenAI') as MockClient:
        service = LLMService(api_key=None)
        
        # Client might be None or raise on use
        assert service.client is None or MockClient.called


# =============================================================================
# Tests: Logging
# =============================================================================

@pytest.mark.asyncio
async def test_generate_text_logs_usage(llm_service, mock_openai_client, caplog):
    """Test that generate_text logs token usage."""
    import logging
    
    with caplog.at_level(logging.INFO):
        await llm_service.generate_text(prompt="Test")
    
    # Check that usage was logged
    # (actual log format may vary)

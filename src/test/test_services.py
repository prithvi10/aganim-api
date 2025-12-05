import pytest
from unittest.mock import patch, MagicMock
from src.main.services import OpenAIService

@pytest.fixture
def mock_openai_client():
    with patch("services.OpenAI") as mock_openai:
        yield mock_openai

def test_generate_copy_success(mock_openai_client):
    """Test successful copy generation."""
    # Setup mock response
    mock_instance = mock_openai_client.return_value
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Generated Copy"))
    ]
    mock_instance.chat.completions.create.return_value = mock_response

    service = OpenAIService()
    result = service.generate_copy(
        product_name="Test Product",
        category="Test Category",
        japanese_description="Japanese Text"
    )

    assert result == "Generated Copy"
    
    # Verify calls
    mock_instance.chat.completions.create.assert_called_once()
    call_kwargs = mock_instance.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["max_tokens"] == 500






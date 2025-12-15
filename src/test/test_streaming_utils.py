import pytest
from unittest.mock import MagicMock, patch
from src.main.service.streaming_utils import stream_openai_response

@pytest.mark.asyncio
async def test_stream_openai_response_logic():
    """Test that the generator yields content and updates usage correctly."""
    
    # Mock OpenAI Service
    mock_service = MagicMock()
    
    # Mock Stream Chunks
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content="Hello "))]
    chunk1.usage = None
    
    chunk2 = MagicMock()
    chunk2.choices = [MagicMock(delta=MagicMock(content="World"))]
    chunk2.usage = MagicMock(total_tokens=5) # Usage reported in last chunk
    
    # Make generate_copy_stream behave like an iterator
    mock_service.generate_copy_stream.return_value = iter([chunk1, chunk2])
    
    # Mock DB Session and Update Function
    mock_db = MagicMock()
    user_id = 1 # Changed from api_key_id
    billing_start = "2023-01-01"
    
    # We need to patch the DB update function since it's imported in the util
    with patch("src.main.service.streaming_utils.update_token_usage") as mock_update:
        
        generator = stream_openai_response(
            openai_service=mock_service,
            product_name="Test",
            category="Test",
            japanese_description="Test",
            db=mock_db,
            user_id=user_id,
            billing_cycle_start=billing_start
        )
        
        # Collect yielded content
        content = []
        async for item in generator:
            content.append(item)
            
        # Verify content
        assert "".join(content) == "Hello World"
        
        # Verify DB Update was called with the correct token count (5) and user_id
        mock_update.assert_called_once_with(mock_db, user_id, 5, billing_start)

@pytest.mark.asyncio
async def test_stream_openai_response_error_handling():
    """Test graceful error handling during stream."""
    mock_service = MagicMock()
    
    # Mock iterator behavior that raises exception
    mock_iterator = MagicMock()
    mock_iterator.__iter__.side_effect = Exception("Stream Error")
    mock_service.generate_copy_stream.return_value = mock_iterator

    mock_db = MagicMock()
    
    generator = stream_openai_response(
        openai_service=mock_service,
        product_name="Test",
        category="Test",
        japanese_description="Test",
        db=mock_db,
        user_id=1,
        billing_cycle_start="2023-01-01"
    )
    
    content = []
    async for item in generator:
        content.append(item)
    
    # The util catches Exception and yields an error message
    assert "Error generating response" in "".join(content)
    assert "Stream Error" in "".join(content)

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
    api_key_id = 1
    billing_start = "2023-01-01"
    
    # We need to patch the DB update function since it's imported in the util
    with patch("src.main.service.streaming_utils.update_token_usage") as mock_update:
        
        generator = stream_openai_response(
            openai_service=mock_service,
            product_name="Test",
            category="Test",
            japanese_description="Test",
            db=mock_db,
            api_key_id=api_key_id,
            billing_cycle_start=billing_start
        )
        
        # Collect yielded content
        content = []
        async for item in generator:
            content.append(item)
            
        # Verify content
        assert "".join(content) == "Hello World"
        
        # Verify DB Update was called with the correct token count (5)
        mock_update.assert_called_once_with(mock_db, api_key_id, 5, billing_start)

@pytest.mark.asyncio
async def test_stream_openai_response_error_handling():
    """Test graceful error handling during stream."""
    mock_service = MagicMock()
    
    # Create a generator that raises an exception immediately
    def error_generator(*args, **kwargs):
        raise Exception("Stream Error")
        yield "should not reach here"

    # When generate_copy_stream is called, it should return our error_generator (or raise when iterated)
    # But in the implementation: stream = openai_service.generate_copy_stream(...)
    # If that call *returns* a generator object without raising, the exception happens during iteration.
    # If that call *raises*, it's caught by the try-except block inside stream_openai_response ONLY if 
    # the try-except wraps the initial call.
    
    # Looking at streaming_utils.py, the try-except block starts AFTER the initial call.
    # So if generate_copy_stream raises immediately, stream_openai_response will crash (propagate error).
    # If generate_copy_stream returns a generator that raises on next(), it is caught.
    
    # Let's mock it to behave like the OpenAI client: returning an iterator that raises during iteration.
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
        api_key_id=1,
        billing_cycle_start="2023-01-01"
    )
    
    content = []
    try:
        async for item in generator:
            content.append(item)
    except Exception:
        pass # Should be caught internally but let's see
    
    # The util catches Exception and yields an error message
    assert "Error generating response" in "".join(content)
    assert "Stream Error" in "".join(content)

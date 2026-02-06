import pytest
from unittest.mock import MagicMock, patch
from src.main.services.openai_legacy_service import OpenAIService

@pytest.mark.asyncio
async def test_stream_openai_response_logic():
    """Test that the generator yields content and updates usage correctly."""
    
    # Mock OpenAI Service
    service = OpenAIService()
    
    # Mock Stream Chunks
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content="Hello "))]
    chunk1.usage = None
    
    chunk2 = MagicMock()
    chunk2.choices = [MagicMock(delta=MagicMock(content="World"))]
    chunk2.usage = MagicMock(total_tokens=5) # Usage reported in last chunk
    
    # Mock generate_copy_stream instead of trying to mock the whole class
    with patch.object(OpenAIService, 'generate_copy_stream', return_value=iter([chunk1, chunk2])):
        # Mock DB Session and Update Function
        mock_db = MagicMock()
        shop_domain = "test-shop.myshopify.com"
        
        # We need to patch the DB update function since it's imported in the service
        with patch("src.main.services.openai_legacy_service.increment_monthly_rewrites_used") as mock_inc:
            
            generator = service.stream_openai_response(
                product_name="Test",
                category="Test",
                japanese_description="Test",
                db=mock_db,
                shop_domain=shop_domain,
            )
            
            # Collect yielded content
            content = []
            async for item in generator:
                content.append(item)
                
            # Verify content
            assert "".join(content) == "Hello World"
            
            # Verify rewrite increment was called once after stream completed
            mock_inc.assert_called_once_with(mock_db, shop_domain, amount=1)

@pytest.mark.asyncio
async def test_stream_openai_response_error_handling():
    """Test graceful error handling during stream."""
    service = OpenAIService()
    
    # Mock iterator behavior that raises exception
    mock_iterator = MagicMock()
    mock_iterator.__iter__.side_effect = Exception("Stream Error")
    
    with patch.object(OpenAIService, 'generate_copy_stream', return_value=mock_iterator):
        mock_db = MagicMock()
        
        generator = service.stream_openai_response(
            product_name="Test",
            category="Test",
            japanese_description="Test",
            db=mock_db,
            shop_domain="test-shop.myshopify.com",
        )
        
        content = []
        async for item in generator:
            content.append(item)
        
        # The service catches Exception and yields an error message
        assert "Error generating response" in "".join(content)
        assert "Stream Error" in "".join(content)

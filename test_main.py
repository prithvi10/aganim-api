from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app

client = TestClient(app)

def test_generate_copy_success():
    # Mock data
    mock_request_data = {
        "product_name": "Test Product",
        "japanese_description": "This is a test description in Japanese.",
        "category": "Test Category"
    }
    
    mock_openai_response = MagicMock()
    mock_openai_response.choices = [
        MagicMock(message=MagicMock(content="This is the generated English copy."))
    ]

    # Patch the OpenAI client's create method
    # Note: We need to patch 'main.client.chat.completions.create'
    with patch("main.client.chat.completions.create", return_value=mock_openai_response) as mock_create:
        response = client.post("/api/generate-copy", json=mock_request_data)
        
        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "english_copy": "This is the generated English copy."
        }
        
        # Verify the mock was called
        mock_create.assert_called_once()

def test_generate_copy_validation_error():
    # Missing required field 'japanese_description'
    mock_request_data = {
        "product_name": "Test Product",
        "category": "Test Category"
    }
    
    response = client.post("/api/generate-copy", json=mock_request_data)
    
    assert response.status_code == 422

def test_generate_copy_openai_error():
    mock_request_data = {
        "product_name": "Test Product",
        "japanese_description": "This is a test description.",
        "category": "Test Category"
    }
    
    # Simulate an exception from OpenAI
    with patch("main.client.chat.completions.create", side_effect=Exception("OpenAI API Error")):
        response = client.post("/api/generate-copy", json=mock_request_data)
        
        assert response.status_code == 500
        assert "OpenAI API Error" in response.json()["detail"]


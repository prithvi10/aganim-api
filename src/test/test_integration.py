import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import User, Plan, APIKey, UsageRecord
from src.main.security.security import get_api_key_hash, hash_api_key

# 1. Setup In-Memory Integration DB
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL, 
    connect_args={"check_same_thread": False}, 
    poolclass=pool.StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def override_get_api_key_hash():
    # Return the known hash of "integration_key_123"
    return hash_api_key("integration_key_123")

@pytest.fixture(scope="module")
def client():
    # Create tables once for the module
    Base.metadata.create_all(bind=engine)
    
    # Override dependencies locally for this test module logic
    # Note: Ideally this should be per-function or managed better, 
    # but since we are running integration tests that depend on specific DB state, 
    # let's set it here and clear it after.
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_api_key_hash] = override_get_api_key_hash
    
    with TestClient(app) as c:
        yield c
        
    # Cleanup overrides
    del app.dependency_overrides[get_db]
    del app.dependency_overrides[get_api_key_hash]
    
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

@pytest.fixture
def setup_data():
    db = TestingSessionLocal()
    
    # Reset tables
    db.query(UsageRecord).delete()
    db.query(APIKey).delete()
    db.query(User).delete()
    db.query(Plan).delete()
    db.commit()

    plan = Plan(name="Integration Plan", monthly_token_quota=1000, max_request_rate=100, can_stream_responses=True)
    db.add(plan)
    db.commit()
    
    user = User(username="integration_user", plan_id=plan.id)
    db.add(user)
    db.commit()
    
    raw_key = "integration_key_123"
    # Ensure hash matches what `src.main.security.security` uses
    key_hash = hash_api_key(raw_key)
    
    api_key = APIKey(user_id=user.id, key_hash=key_hash, is_active=True)
    db.add(api_key)
    db.commit()
    
    db.close()
    return raw_key

def test_integration_generate_copy_flow(client, setup_data):
    """
    End-to-End Test:
    1. Request with valid API Key.
    2. Controller verifies DB quota (Real DB).
    3. Controller calls OpenAI (Mocked).
    4. Controller updates DB usage (Real DB).
    5. Response returned.
    """
    api_key = setup_data
    
    # Mock OpenAI to avoid external calls and costs
    mock_openai_response = MagicMock()
    mock_openai_response.choices = [MagicMock(message=MagicMock(content="Integration Success"))]
    mock_openai_response.usage.total_tokens = 50

    # Ensure we patch the correct path for OpenAIService instance in controller
    with patch("src.main.api.controller.openai_service.generate_copy", return_value=mock_openai_response) as mock_generate:
        
        response = client.post(
            "/api/generate-copy",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "product_name": "Integration Product",
                "japanese_description": "Testing the whole flow.",
                "category": "Integration"
            }
        )
        
        # 1. Check Response
        assert response.status_code == 200
        assert response.json()["english_copy"] == "Integration Success"
        
        # 2. Verify OpenAI was called
        mock_generate.assert_called_once()
        
        # 3. Verify DB Update (Usage should be 50)
        db = TestingSessionLocal()
        user = db.query(User).filter_by(username="integration_user").first()
        key = user.api_keys[0]
        
        usage_record = db.query(UsageRecord).filter_by(api_key_id=key.id).first()
        assert usage_record is not None
        assert usage_record.token_count == 50
        db.close()

def test_integration_quota_exceeded(client, setup_data):
    """Test that the DB correctly blocks requests when quota is exceeded."""
    api_key = setup_data
    
    # Manually set usage to limit (1000)
    db = TestingSessionLocal()
    user = db.query(User).filter_by(username="integration_user").first()
    key = user.api_keys[0]
    
    # Ensure record exists (it might be created in previous test or needs creation)
    usage_record = db.query(UsageRecord).filter_by(api_key_id=key.id).first()
    if not usage_record:
        from datetime import date
        today = date.today()
        cycle_start = date(today.year, today.month, 1)
        usage_record = UsageRecord(api_key_id=key.id, billing_cycle_start=cycle_start, token_count=0)
        db.add(usage_record)
    
    usage_record.token_count = 1000
    db.commit()
    db.close()
    
    # Request should fail
    response = client.post(
        "/api/generate-copy",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "product_name": "Blocked Product",
            "japanese_description": "Should fail."
        }
    )
    
    assert response.status_code == 429
    assert "Monthly token quota exceeded" in response.json()["detail"]

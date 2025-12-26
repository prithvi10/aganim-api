import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

from src.main.api.main import app
from src.main.db.database import Base, get_db
from src.main.db.db_models import User, Plan, UsageRecord, Shop
# Removed APIKey import and key hashing

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

@pytest.fixture(scope="module")
def client():
    # Create tables once for the module
    Base.metadata.create_all(bind=engine)
    
    # Override dependencies locally
    app.dependency_overrides[get_db] = override_get_db
    # Removed api key override
    
    with TestClient(app) as c:
        yield c
        
    # Cleanup overrides
    del app.dependency_overrides[get_db]
    
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

@pytest.fixture
def setup_data():
    db = TestingSessionLocal()
    
    # Reset tables
    db.query(UsageRecord).delete()
    db.query(User).delete()
    db.query(Plan).delete()
    db.query(Shop).delete()
    db.commit()

    plan = Plan(name="Integration Plan", monthly_token_quota=1000, max_request_rate=100, can_stream_responses=True)
    db.add(plan)
    db.commit()
    
    user = User(username="integration-shop.myshopify.com", plan_id=plan.id)
    db.add(user)
    db.commit()
    
    shop = Shop(domain="integration-shop.myshopify.com", access_token="integration_token")
    db.add(shop)
    db.commit()
    
    db.close()
    return "integration-shop.myshopify.com"

def test_integration_generate_copy_flow(client, setup_data):
    """
    End-to-End Test:
    1. Request via Proxy (Shop Domain).
    2. Controller verifies DB quota (Real DB).
    3. Controller calls OpenAI (Mocked).
    4. Controller updates DB usage (Real DB).
    5. Response returned.
    """
    shop_domain = setup_data
    
    # Mock OpenAI
    mock_openai_response = MagicMock()
    mock_openai_response.choices = [MagicMock(message=MagicMock(content='{"title": "Int Title", "description": "Int Desc"}'))]
    mock_openai_response.usage.total_tokens = 50

    with patch("src.main.core.generation.openai_service.generate_copy", return_value=mock_openai_response) as mock_generate:
        
        # Use proxy endpoint (manual shop extraction)
        response = client.post(
            f"/api/proxy/generate-copy?shop={shop_domain}",
            json={
                "product_name": "Integration Product",
                "japanese_description": "Testing the whole flow.",
                "category": "Integration"
            }
        )
        
        # 1. Check Response
        assert response.status_code == 200
        json_resp = response.json()
        assert json_resp["status"] == "success"
        assert json_resp["data"]["title"] == "Int Title"
        assert json_resp["data"]["description"] == "Int Desc"
        
        # 2. Verify OpenAI was called
        mock_generate.assert_called_once()
        
        # 3. Verify DB Update (Usage should be 50)
        db = TestingSessionLocal()
        user = db.query(User).filter_by(username=shop_domain).first()
        
        usage_record = db.query(UsageRecord).filter_by(user_id=user.id).first()
        assert usage_record is not None
        assert usage_record.token_count == 50
        db.close()

def test_integration_quota_exceeded(client, setup_data):
    """Test that the DB correctly blocks requests when quota is exceeded."""
    shop_domain = setup_data
    
    # Manually set usage to limit (1000)
    db = TestingSessionLocal()
    user = db.query(User).filter_by(username=shop_domain).first()
    
    # Create record with MAX quota usage
    from datetime import date
    today = date.today()
    cycle_start = date(today.year, today.month, 1)
    
    usage_record = UsageRecord(user_id=user.id, billing_cycle_start=cycle_start, token_count=1000)
    db.add(usage_record)
    
    db.commit()
    db.close()
    
    # Request should fail
    response = client.post(
        f"/api/proxy/generate-copy?shop={shop_domain}",
        json={
            "product_name": "Blocked Product",
            "japanese_description": "Should fail."
        }
    )
    
    assert response.status_code == 429
    assert "Monthly token quota exceeded" in response.json()["detail"]

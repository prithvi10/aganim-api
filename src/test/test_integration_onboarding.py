import json
import hashlib
import hmac
import base64
from unittest.mock import patch
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker
from src.main.api.main import app
from src.main.db.database import Base
from src.main.db.db_models import User, Plan

# Setup In-Memory Integration DB
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL, 
    connect_args={"check_same_thread": False}, 
    poolclass=pool.StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_integration_onboarding_webhook_flow():
    """
    Integration Test for User Onboarding via Webhook:
    1. Seed 'Basic Plan' in DB.
    2. Send valid Webhook request with HMAC.
    3. Verify User is created in DB.
    """
    
    # 1. Setup DB
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # Seed Plan
    plan = Plan(name="Basic", monthly_token_quota=50000, max_request_rate=60)
    db.add(plan)
    db.commit()
    plan_id = plan.id # Capture ID before closing session
    db.close()

    # 2. Prepare Webhook Request
    # Use real logic for HMAC generation to test verify_webhook_signature
    secret = "test_integration_secret"
    payload = {
        "myshopify_domain": "integration-store.myshopify.com",
        "billing_plan": "Basic",
        "email": "integration@example.com"
    }
    json_body = json.dumps(payload).encode('utf-8')
    
    digest = hmac.new(secret.encode('utf-8'), json_body, hashlib.sha256).digest()
    hmac_sig = base64.b64encode(digest).decode('utf-8')
    
    headers = {"X-Shopify-Hmac-Sha256": hmac_sig}

    # 3. Use TestClient with overrides
    from fastapi.testclient import TestClient
    from src.main.db.database import get_db
    
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    
    # We must patch the SECRET env var used in security.py
    # We patch it where it is IMPORTED or used.
    # Since security.py loads it at module level, patching os.getenv won't work if already loaded.
    # We patch the variable in the module directly.
    with patch("src.main.security.security.SHOPIFY_API_SECRET", secret):
        with TestClient(app) as client:
            response = client.post(
                "/webhooks/subscription-activated",
                content=json_body,
                headers=headers
            )
            
            # 4. Assert Response
            assert response.status_code == 200

            # 5. Verify DB Side Effects
            db = TestingSessionLocal()
            
            # Check User
            user = db.query(User).filter_by(username="integration-store.myshopify.com").first()
            assert user is not None
            assert user.email == "integration@example.com"
            assert user.plan_id == plan_id
            
            # No API Key check anymore
            
            db.close()
    
    # Cleanup
    Base.metadata.drop_all(bind=engine)


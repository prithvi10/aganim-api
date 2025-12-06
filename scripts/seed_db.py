import sys
import os
from sqlalchemy.orm import Session
from src.main.db.database import SessionLocal, engine, Base
from src.main.db.db_models import Plan, User, APIKey
from src.main.security.security import hash_api_key

def seed_data():
    db = SessionLocal()
    try:
        # 1. Create Plans
        basic_plan = db.query(Plan).filter(Plan.name == "Basic Agent").first()
        if not basic_plan:
            basic_plan = Plan(
                name="Basic Agent",
                price_usd_monthly=29.99,
                monthly_token_quota=50000, # 50k tokens
                max_request_rate=60
            )
            db.add(basic_plan)
            db.commit()
            db.refresh(basic_plan)
            print("✅ Created Basic Plan")

        # 2. Create Test User
        test_user = db.query(User).filter(User.username == "dev-shop.myshopify.com").first()
        if not test_user:
            test_user = User(
                username="dev-shop.myshopify.com",
                email="dev@example.com",
                plan_id=basic_plan.id
            )
            db.add(test_user)
            db.commit()
            db.refresh(test_user)
            print("✅ Created Test User")

        # 3. Create Test API Key
        # Raw key: "dev-token-123"
        raw_key = "dev-token-123"
        key_hash = hash_api_key(raw_key)
        
        test_key = db.query(APIKey).filter(APIKey.key_hash == key_hash).first()
        if not test_key:
            test_key = APIKey(
                user_id=test_user.id,
                key_hash=key_hash,
                is_active=True
            )
            db.add(test_key)
            db.commit()
            print(f"✅ Created Test API Key (Raw: {raw_key})")
        
    except Exception as e:
        print(f"❌ Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    seed_data()


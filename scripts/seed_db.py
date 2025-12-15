import sys
import os

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from src.main.db.database import SessionLocal, engine, Base
from src.main.db.db_models import Plan, User, Shop

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
        shop_domain = "dev-shop.myshopify.com"
        test_user = db.query(User).filter(User.username == shop_domain).first()
        if not test_user:
            test_user = User(
                username=shop_domain,
                email="dev@example.com",
                plan_id=basic_plan.id
            )
            db.add(test_user)
            db.commit()
            db.refresh(test_user)
            print("✅ Created Test User")

        # 3. Create Shop Record (for OAuth/Proxy)
        test_shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        if not test_shop:
            test_shop = Shop(
                domain=shop_domain,
                access_token="dev-token-123"
            )
            db.add(test_shop)
            db.commit()
            print(f"✅ Created Test Shop Record for {shop_domain}")
        
    except Exception as e:
        print(f"❌ Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    seed_data()


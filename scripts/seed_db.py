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
        # 1. Create New Plans
        plans = [
            {"name": "Basic", "price": 9.90, "quota": 100000, "rate": 60, "stream": False},
            {"name": "Standard", "price": 29.90, "quota": 500000, "rate": 120, "stream": False},
            {"name": "Pro", "price": 69.90, "quota": 5000000, "rate": 300, "stream": True},
        ]

        for p_data in plans:
            existing = db.query(Plan).filter(Plan.name == p_data["name"]).first()
            if not existing:
                plan = Plan(
                    name=p_data["name"],
                    price_usd_monthly=p_data["price"],
                    monthly_token_quota=p_data["quota"],
                    max_request_rate=p_data["rate"],
                    can_stream_responses=p_data["stream"],
                    is_active=True
            )
                db.add(plan)
                print(f"✅ Created {p_data['name']} Plan")
        
            db.commit()

        # 2. Create Test User (linked to Basic)
        basic_plan = db.query(Plan).filter(Plan.name == "Basic").first()
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

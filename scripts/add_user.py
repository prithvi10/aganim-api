import sys
import os

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from src.main.db.database import SessionLocal, engine, Base
from src.main.db.db_models import Plan, User, Shop

def add_custom_user():
    db = SessionLocal()
    try:
        # 1. Create Custom Plan
        plan_name = "Restricted Starter"
        custom_plan = db.query(Plan).filter(Plan.name == plan_name).first()
        if not custom_plan:
            custom_plan = Plan(
                name=plan_name,
                price_usd_monthly=5.00,
                monthly_rewrite_limit=100,      # 100 tokens
                max_request_rate=3,           # 3 requests per month (effectively) or minute depending on logic
                can_stream_responses=False    # No streaming
            )
            db.add(custom_plan)
            db.commit()
            db.refresh(custom_plan)
            print(f"✅ Created Plan: {plan_name}")
        else:
             print(f"ℹ️ Plan '{plan_name}' already exists. Using ID: {custom_plan.id}")

        # 2. Create User (User ID 2 ideally, but auto-increment will handle)
        username = "restricted-user.myshopify.com"
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(
                username=username,
                email="restricted@example.com",
                plan_id=custom_plan.id
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"✅ Created User: {username} (ID: {user.id})")
        else:
            print(f"ℹ️ User '{username}' already exists. Updating plan.")
            user.plan_id = custom_plan.id
            db.commit()

        # 3. Create Shop Record (for access token)
        shop = db.query(Shop).filter(Shop.domain == username).first()
        token = "restricted-token-456"
        if not shop:
            shop = Shop(
                domain=username,
                access_token=token
            )
            db.add(shop)
            db.commit()
            print(f"✅ Created Shop Record for user. Token: {token}")
        else:
            print(f"ℹ️ Shop '{username}' already exists. Updating token.")
            shop.access_token = token
            db.commit()
        
    except Exception as e:
        print(f"❌ Error adding user: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    add_custom_user()


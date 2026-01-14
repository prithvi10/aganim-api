import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import date

from src.main.db.database import Base
from src.main.db.db_models import User, Plan, UsageRecord, Shop
from src.main.api.validation import validate_shop_and_quota
from fastapi import HTTPException

# Setup In-Memory DB
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

def setup_data():
    print("--- Setting up Test Data ---")
    # 1. Plan
    plan = Plan(name="Proxy Plan", monthly_rewrite_limit=1000, max_request_rate=10, is_active=True)
    db.add(plan)
    db.commit()
    print(f"Created Plan: {plan.name}")

    # 2. User
    user = User(username="proxy-shop.myshopify.com", plan_id=plan.id)
    db.add(user)
    db.commit()
    print(f"Created User: {user.username}")

    # 3. Shop
    shop = Shop(domain="proxy-shop.myshopify.com", access_token="some_token")
    db.add(shop)
    db.commit()
    print(f"Created Shop Record")

    return user

def test_validation():
    print("\n--- Testing validate_shop_and_quota ---")
    shop_domain = "proxy-shop.myshopify.com"
    
    try:
        context = validate_shop_and_quota(db, shop_domain)
        print("✅ Validation Successful!")
        print(f"User: {context['user'].username}")
        print(f"Plan: {context['plan'].name}")
        print(f"Usage: {context['current_usage']}")
    except HTTPException as e:
        print(f"❌ Validation Failed: {e.detail}")
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")

    # Test Quota Exceeded
    print("\n--- Testing Quota Exceeded ---")
    # Add usage
    today = date.today()
    cycle_start = date(today.year, today.month, 1)
    
    user = db.query(User).filter_by(username=shop_domain).first()
    
    usage = UsageRecord(
        user_id=user.id,
        billing_cycle_start=cycle_start,
        token_count=1500 # > 1000
    )
    db.add(usage)
    db.commit()
    
    try:
        validate_shop_and_quota(db, shop_domain)
        print("❌ Failed: Should have raised Quota Exceeded")
    except HTTPException as e:
        if e.status_code == 429:
             print(f"✅ Correctly caught Quota Exceeded: {e.detail}")
        else:
             print(f"❌ Wrong status code: {e.status_code}")

if __name__ == "__main__":
    setup_data()
    test_validation()


import sys
import os

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main.db.database import SessionLocal
from src.main.db.db_models import User, Plan

def set_pro_plan(shop_domain: str):
    db = SessionLocal()
    try:
        # 1. Find the Pro Plan
        pro_plan = db.query(Plan).filter(Plan.name == "Pro").first()
        if not pro_plan:
            print("❌ 'Pro' plan not found in database. Please run seed_db.py first.")
            return

        # 2. Find the User by shop domain (username)
        user = db.query(User).filter(User.username == shop_domain).first()
        if not user:
            print(f"❌ User for shop '{shop_domain}' not found. Ensure the app is installed on this shop.")
            return

        # 3. Update the user's plan
        user.plan_id = pro_plan.id
        db.commit()
        print(f"✅ Successfully upgraded '{shop_domain}' to the Pro plan!")
        
    except Exception as e:
        print(f"❌ Error updating plan: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/set_pro_plan.py <shop_domain>")
        print("Example: python scripts/set_pro_plan.py dev-shop.myshopify.com")
    else:
        set_pro_plan(sys.argv[1])


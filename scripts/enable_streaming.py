import sys
import os

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main.db.database import SessionLocal
from src.main.db.db_models import Plan

def enable_streaming():
    db = SessionLocal()
    try:
        plan = db.query(Plan).filter(Plan.name == "Basic Agent").first()
        if plan:
            plan.can_stream_responses = True
            db.commit()
            print(f"✅ Enabled streaming for plan: {plan.name}")
        else:
            print("❌ Plan 'Basic Agent' not found.")
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    enable_streaming()


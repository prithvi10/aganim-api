from src.main.database import SessionLocal
from src.main.db_models import Plan

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


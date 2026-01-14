import sys
import os

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.main.db.database import SessionLocal, engine, Base
from src.main.db.db_models import Plan, User, Shop

def _ensure_plan_columns_exist():
    """
    This project does not currently use migrations, so we opportunistically add new
    plan columns when running the seed script.
    - SQLite: ALTER TABLE ADD COLUMN (no IF NOT EXISTS)
    - Postgres: ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    """
    dialect = engine.dialect.name

    if dialect == "sqlite":
        with engine.connect() as conn:
            cols = conn.execute(text("PRAGMA table_info(plans)")).fetchall()
            existing = {c[1] for c in cols}  # pragma: (cid, name, type, notnull, dflt, pk)

            def add(col_sql: str, col_name: str):
                if col_name in existing:
                    return
                conn.execute(text(f"ALTER TABLE plans ADD COLUMN {col_sql}"))

            add("product_limit INTEGER", "product_limit")
            add("max_locales INTEGER", "max_locales")
            add("features_json TEXT", "features_json")
            conn.commit()
        return

    # Postgres / others
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS product_limit INTEGER"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_locales INTEGER"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS features_json TEXT"))
        conn.commit()

def seed_data():
    db = SessionLocal()
    try:
        # Ensure tables exist
        Base.metadata.create_all(bind=engine)
        _ensure_plan_columns_exist()

        # 1. Create/Update Plans (UPSERT by name)
        plans = [
            {
                "name": "Basic",
                "price": 49.0,
                "product_limit": 50,
                "max_locales": 1,
                "features": ["1 Locale", "SEO optimization", "GPT-4o-mini"],
                "rate": 60,
                "stream": False,
            },
            {
                "name": "Standard",
                "price": 99.0,
                "product_limit": 100,
                "max_locales": -1,
                "features": ["Multi-locale", "Social Hook Architect", "AI Marketing"],
                "rate": 120,
                "stream": False,
            },
            {
                "name": "Pro",
                "price": 199.0,
                "product_limit": -1,  # unlimited
                "max_locales": -1,
                "features": ["Unlimited Bulk Sync", "Priority GPT-5", "Supreme Features"],
                "rate": 300,
                "stream": True,
            },
        ]

        for p_data in plans:
            existing = db.query(Plan).filter(Plan.name == p_data["name"]).first()
            features_json = json.dumps(p_data.get("features", []))

            if not existing:
                existing = Plan(name=p_data["name"])
                db.add(existing)
                print(f"✅ Created {p_data['name']} Plan")
            else:
                print(f"♻️  Updated {p_data['name']} Plan")

            # NOTE: We keep `monthly_token_quota` populated for backward compatibility with older codepaths/UI.
            # It now represents the monthly product/sync limit.
            existing.price_usd_monthly = p_data["price"]
            existing.product_limit = p_data["product_limit"]
            existing.max_locales = p_data["max_locales"]
            existing.features_json = features_json
            existing.monthly_token_quota = p_data["product_limit"]
            existing.max_request_rate = p_data["rate"]
            existing.can_stream_responses = p_data["stream"]
            existing.is_active = True

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
    seed_data()

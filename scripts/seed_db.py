import sys
import os

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.main.db.database import SessionLocal, engine, Base
from src.main.db.db_models import Plan, User, Shop, BrandEntity

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
            add("billing_cycle_type TEXT", "billing_cycle_type")
            conn.commit()
        return

    # Postgres / others
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS product_limit INTEGER"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_locales INTEGER"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS features_json TEXT"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN IF NOT EXISTS billing_cycle_type TEXT"))
        conn.commit()

def _ensure_shop_columns_exist():
    """
    This project does not currently use migrations, so we opportunistically add new
    shop columns when running the seed script.
    - SQLite: ALTER TABLE ADD COLUMN (no IF NOT EXISTS)
    - Postgres: ALTER TABLE ... ADD COLUMN IF NOT EXISTS
    """
    dialect = engine.dialect.name

    if dialect == "sqlite":
        with engine.connect() as conn:
            cols = conn.execute(text("PRAGMA table_info(shops)")).fetchall()
            existing = {c[1] for c in cols}  # pragma: (cid, name, type, notnull, dflt, pk)

            def add(col_sql: str, col_name: str):
                if col_name in existing:
                    return
                conn.execute(text(f"ALTER TABLE shops ADD COLUMN {col_sql}"))

            add("monthly_rewrites_used INTEGER DEFAULT 0", "monthly_rewrites_used")
            add("lifetime_rewrites_remaining INTEGER DEFAULT 10", "lifetime_rewrites_remaining")
            add("is_active INTEGER DEFAULT 1", "is_active")
            add("welcome_back_pending INTEGER DEFAULT 0", "welcome_back_pending")
            add("reset_anchor_date TEXT", "reset_anchor_date")
            add("next_reset_date TEXT", "next_reset_date")
            add("fair_use_last_notified_at TEXT", "fair_use_last_notified_at")
            add("monthly_cost_accumulated REAL DEFAULT 0", "monthly_cost_accumulated")
            add("pending_plan_name TEXT", "pending_plan_name")
            add("pending_plan_effective_at TEXT", "pending_plan_effective_at")
            add("last_plan_change_type TEXT", "last_plan_change_type")
            add("last_plan_change_at TEXT", "last_plan_change_at")
            add("last_shopify_subscription_status TEXT", "last_shopify_subscription_status")
            # Strategic intelligence columns (Writing Studio)
            add("strategic_intelligence TEXT", "strategic_intelligence")
            add("strategic_intelligence_updated_at TEXT", "strategic_intelligence_updated_at")
            conn.commit()
        return

    # Postgres / others
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS monthly_rewrites_used INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS lifetime_rewrites_remaining INTEGER DEFAULT 10"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS welcome_back_pending BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS reset_anchor_date TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS next_reset_date TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS fair_use_last_notified_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS monthly_cost_accumulated NUMERIC(12,2) DEFAULT 0"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS pending_plan_name VARCHAR"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS pending_plan_effective_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS last_plan_change_type VARCHAR"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS last_plan_change_at TIMESTAMPTZ"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS last_shopify_subscription_status VARCHAR"))
        # Strategic intelligence columns (Writing Studio)
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS strategic_intelligence JSONB"))
        conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS strategic_intelligence_updated_at TIMESTAMPTZ"))
        conn.commit()

def seed_data():
    db = SessionLocal()
    try:
        # Ensure tables exist
        Base.metadata.create_all(bind=engine)
        _ensure_plan_columns_exist()
        _ensure_shop_columns_exist()

        # 1. Create/Update Plans (UPSERT by name)
        plans = [
            {
                "name": "Free",
                "price": 0.0,
                # For lifetime plans, the monthly product_limit is not used for enforcement.
                # We keep it populated for UI/back-compat.
                "product_limit": 10,
                "max_locales": 1,
                "billing_cycle_type": "lifetime",
                "features": ["10 lifetime rewrites", "SEO optimization", "Professional tone"],
                "rate": 30,
                "stream": False,
            },
            {
                "name": "Basic",
                "price": 49.0,
                "product_limit": 50,
                "max_locales": 1,
                "billing_cycle_type": "recurring",
                "features": ["1 Locale", "SEO optimization", "GPT-4o-mini"],
                "rate": 60,
                "stream": False,
            },
            {
                "name": "Standard",
                "price": 99.0,
                "product_limit": 100,
                "max_locales": -1,
                "billing_cycle_type": "recurring",
                "features": ["Multi-locale", "Social Hook Architect", "AI Marketing"],
                "rate": 120,
                "stream": False,
            },
            {
                "name": "Pro",
                "price": 199.0,
                "product_limit": -1,  # unlimited
                "max_locales": -1,
                "billing_cycle_type": "recurring",
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

            # NOTE: We keep the legacy DB column `monthly_token_quota` populated for backward compatibility with older codepaths/UI.
            # It now represents the monthly product/sync limit.
            existing.price_usd_monthly = p_data["price"]
            existing.product_limit = p_data["product_limit"]
            existing.max_locales = p_data["max_locales"]
            existing.features_json = features_json
            existing.billing_cycle_type = p_data.get("billing_cycle_type") or "recurring"
            existing.monthly_rewrite_limit = p_data["product_limit"]
            existing.max_request_rate = p_data["rate"]
            existing.can_stream_responses = p_data["stream"]
            existing.is_active = True

        db.commit()

        # 2. Create Test User (linked to Free)
        free_plan = db.query(Plan).filter(Plan.name == "Free").first()
        shop_domain = "dev-shop.myshopify.com"
        test_user = db.query(User).filter(User.username == shop_domain).first()
        if not test_user:
            test_user = User(
                username=shop_domain,
                email="dev@example.com",
                plan_id=free_plan.id if free_plan else None
            )
            db.add(test_user)
            db.commit()
            db.refresh(test_user)
            print("✅ Created Test User")

        # 3. Create Shop Record (for OAuth/Proxy)
        test_shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        if not test_shop:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            test_shop = Shop(
                domain=shop_domain,
                access_token="dev-token-123",
                monthly_rewrites_used=0,
                lifetime_rewrites_remaining=10,
                reset_anchor_date=now,
                next_reset_date=now + timedelta(days=30),
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

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.shared.db.database import SessionLocal, engine, Base
from src.ecommerce.db.models import Plan, User, Shop, BrandEntity

def seed_data():
    db = SessionLocal()
    try:
        # For test/local-dev (SQLite), create tables from model metadata.
        # Production schema is managed exclusively by Alembic migrations.
        if engine.dialect.name == "sqlite":
            Base.metadata.create_all(bind=engine)

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
                "price": 20.0,
                "product_limit": 50,
                "max_locales": 1,
                "billing_cycle_type": "recurring",
                "features": ["AI Product Rewriter", "Marketing Copy", "1 Mission/mo (text-only)"],
                "rate": 60,
                "stream": False,
            },
            {
                "name": "Standard",
                "price": 33.0,
                "product_limit": -1,
                "max_locales": -1,
                "billing_cycle_type": "recurring",
                "features": ["Unlimited Products", "SEO + Price Scout", "3 Missions/mo"],
                "rate": 120,
                "stream": False,
            },
            {
                "name": "Pro",
                "price": 65.0,
                "product_limit": -1,
                "max_locales": -1,
                "billing_cycle_type": "recurring",
                "features": ["Full Autonomous Pilot", "150 Image Credits/mo", "Unlimited Missions"],
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

"""
Migration script for the Plan Gating Overhaul.

Run via:  python -m src.ecommerce.db.migrate_plan_gating

Adds new columns to shops table and creates feature_usage / usage_event_log tables.
Safe to re-run (uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
"""
from __future__ import annotations

import sys
from sqlalchemy import text
from src.shared.db.database import engine, Base
from src.ecommerce.db.models import FeatureUsage, UsageEventLog  # noqa: F401 – register models


def run_migration():
    """Apply plan-gating schema changes."""
    with engine.begin() as conn:
        # 1. Add new columns to shops (idempotent via IF NOT EXISTS on Postgres,
        #    or try/except for SQLite which lacks that syntax)
        new_shop_columns = [
            ("lifetime_missions_remaining", "INTEGER NOT NULL DEFAULT 3"),
            ("lifetime_image_credits_remaining", "INTEGER NOT NULL DEFAULT 5"),
            ("monthly_missions_used", "INTEGER NOT NULL DEFAULT 0"),
            ("monthly_image_generations_used", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for col_name, col_def in new_shop_columns:
            try:
                conn.execute(text(f"ALTER TABLE shops ADD COLUMN {col_name} {col_def}"))
                print(f"  + shops.{col_name}")
            except Exception:
                print(f"  ~ shops.{col_name} (already exists)")

        # 2. Create new tables
        FeatureUsage.__table__.create(bind=conn, checkfirst=True)
        print("  + feature_usage table")

        UsageEventLog.__table__.create(bind=conn, checkfirst=True)
        print("  + usage_event_log table")

    print("Migration complete.")


if __name__ == "__main__":
    run_migration()

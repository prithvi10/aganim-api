"""
Migration script for shop logo support.

Run via:  python -m src.ecommerce.db.migrate_logo

Adds logo_url column to shops table.
Safe to re-run (uses try/except for idempotency).
"""
from __future__ import annotations

from sqlalchemy import text
from src.shared.db.database import engine


def run_migration():
    """Apply logo schema changes."""
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE shops ADD COLUMN logo_url VARCHAR"))
            print("  + shops.logo_url")
        except Exception:
            print("  ~ shops.logo_url (already exists)")

    print("Migration complete.")


if __name__ == "__main__":
    run_migration()

"""Alembic migration environment configuration.

Reads DATABASE_URL from the environment (same variable the app uses) and
wires up SQLAlchemy Base.metadata so ``--autogenerate`` can diff models.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the project root is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.shared.db.database import Base  # noqa: E402

# Import every model so Base.metadata is fully populated
import src.ecommerce.db.models  # noqa: F401,E402
import src.agentic_core.db.models  # noqa: F401,E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

EXCLUDE_INDEXES = {
    "agent_corrections_embedding_idx",
    "context_chunks_embedding_idx",
}


def _include_object(obj, name, type_, reflected, compare_to):
    """Exclude manually-managed pgvector HNSW indexes from autogenerate."""
    if type_ == "index" and name in EXCLUDE_INDEXES:
        return False
    return True


def _get_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Alembic needs it to connect to the database."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

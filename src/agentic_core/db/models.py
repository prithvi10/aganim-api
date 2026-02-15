"""
Agentic Core DB models.

These tables use generic column names (tenant_id, resource_id, tier)
and have NO foreign keys to Shopify-specific tables.

When agentic_core is extracted into a microservice, these models
travel with it and get their own database.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.orm import synonym
from sqlalchemy.dialects.postgresql import JSONB
try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    from sqlalchemy.types import TypeDecorator, JSON as _JSON
    import warnings

    warnings.warn(
        "pgvector not installed; falling back to JSON for Vector column types.",
        RuntimeWarning,
    )

    class Vector(TypeDecorator):
        impl = _JSON
        cache_ok = True

        def __init__(self, *args, **kwargs):
            super().__init__()

from sqlalchemy.types import Text as TextType
from sqlalchemy.sql import func
from src.shared.db.database import Base


class Mission(Base):
    """
    Tracks long-running agent missions for a resource.

    A mission represents a complete optimization workflow
    that may involve multiple agents.
    """
    __tablename__ = "missions"

    id = Column(String, primary_key=True)  # UUID
    tenant_id = Column(String, index=True, nullable=False)      # was shop_id
    resource_id = Column(String, index=True, nullable=False)    # was product_id

    # Backward-compat synonyms (ecommerce code may still use old names)
    shop_id = synonym("tenant_id")
    product_id = synonym("resource_id")

    # Current mission status
    # Values: PENDING, IN_PROGRESS, WAITING_APPROVAL, COMPLETED, ERROR
    status = Column(String, nullable=False, default="PENDING")

    # Serialized MissionState (full snapshot for resumption)
    current_state = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    # Agent execution logs for debugging/audit
    logs = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    # Plan tier that was active when mission started (for routing)
    tier = Column(String, nullable=True)                        # was plan_tier

    # Backward-compat synonym
    plan_tier = synonym("tier")

    # Error tracking
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class AgentCorrection(Base):
    """
    Stores user corrections to agent outputs for learning.
    """
    __tablename__ = "agent_corrections"

    id = Column(String, primary_key=True)  # UUID
    tenant_id = Column(String, index=True, nullable=False)      # was shop_id

    # Backward-compat synonym
    shop_id = synonym("tenant_id")

    # Which agent produced the original output
    agent_role = Column(String, nullable=False)

    # The original AI-generated output
    original_output = Column(Text, nullable=False)

    # What the user changed it to
    user_correction = Column(Text, nullable=False)

    # Embedding for semantic similarity search
    embedding = Column(Vector(1536).with_variant(TextType, "sqlite"), nullable=True)

    # Context
    resource_id = Column(String, index=True, nullable=True)     # was product_id
    context_metadata = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    # Backward-compat synonym
    product_id = synonym("resource_id")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ContextChunk(Base):
    """
    Generic RAG vector store -- replaces StoreContext for agentic_core.
    """
    __tablename__ = "context_chunks"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True, nullable=False)      # was shop_id
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536).with_variant(TextType, "sqlite"), nullable=False)
    metadata_json = Column("metadata", JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Backward-compat synonym
    shop_id = synonym("tenant_id")

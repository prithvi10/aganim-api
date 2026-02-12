from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Date, BigInteger, Numeric, Text, JSON
from sqlalchemy.types import Text as TextType
from sqlalchemy.dialects.postgresql import JSONB
try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover - fallback for local/dev environments without pgvector
    from sqlalchemy.types import TypeDecorator, JSON
    import warnings

    warnings.warn(
        "pgvector not installed; falling back to JSON for Vector column types.",
        RuntimeWarning,
    )

    class Vector(TypeDecorator):
        impl = JSON
        cache_ok = True

        def __init__(self, *args, **kwargs):
            super().__init__()
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Link to active plan
    plan_id = Column(Integer, ForeignKey("plans.id"))
    
    # Relationships
    plan = relationship("Plan", back_populates="users")
    # DIRECT relationship to usage records (No more API Keys)
    usage_records = relationship("UsageRecord", back_populates="user")

class Shop(Base):
    """
    Stores Shopify Shop details including access tokens.
    Used for OAuth flow and offline access.
    """
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, unique=True, index=True) # e.g., 'my-shop.myshopify.com'
    access_token = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    # -----------------------------------------------------------------------------
    # Product-based usage gating (replaces token-based UsageRecord metering)
    # -----------------------------------------------------------------------------
    monthly_rewrites_used = Column(Integer, nullable=False, default=0, server_default="0")
    # Lifetime free-tier credits (NEVER resets). Only used when plan is Free (billing_cycle_type="lifetime").
    lifetime_rewrites_remaining = Column(Integer, nullable=False, default=10, server_default="10")
    # App install state (used for reinstall flows). We do NOT delete shop rows on uninstall.
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    # One-shot UI hint: set True when a previously-known shop reinstalls; UI can show "Welcome back" once.
    welcome_back_pending = Column(Boolean, nullable=False, default=False, server_default="0")
    # -----------------------------------------------------------------------------
    # High-integrity reinstall & paid grace period support
    # -----------------------------------------------------------------------------
    # For paid plans: the hard expiry of the last paid billing cycle (even if Shopify cancels on uninstall).
    access_expires_at = Column(DateTime(timezone=True), nullable=True)
    # The plan the merchant is currently considered on (internal source of truth for gating UX).
    # NOTE: This is intentionally separate from Shopify activeSubscriptions which may be empty after uninstall.
    current_plan_name = Column(String, nullable=True)
    # Remembers the last known plan tier across uninstall/reinstall (used for grace period + routing).
    last_plan_name = Column(String, nullable=True)
    # Tracks whether the merchant actually uninstalled (used to display "Grace" only for reinstall scenarios).
    last_uninstalled_at = Column(DateTime(timezone=True), nullable=True)
    # The date the merchant installed or last changed plans.
    reset_anchor_date = Column(DateTime(timezone=True), nullable=True)
    # Computed as reset_anchor_date + 30 days (self-healed forward as needed).
    next_reset_date = Column(DateTime(timezone=True), nullable=True)

    # -----------------------------------------------------------------------------
    # Internal fair-use monitoring (NEVER shown to merchant)
    # -----------------------------------------------------------------------------
    fair_use_last_notified_at = Column(DateTime(timezone=True), nullable=True)
    monthly_cost_accumulated = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")

    # -----------------------------------------------------------------------------
    # Onboarding (UI wizard progress; safe to expose to merchant)
    # -----------------------------------------------------------------------------
    # 0..4 (4 = completed)
    onboarding_step = Column(Integer, nullable=False, default=0, server_default="0")
    is_onboarding_finished = Column(Boolean, nullable=False, default=False, server_default="0")
    # Brand context blob (generated during onboarding ingestion)
    brand_context = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    brand_context_updated_at = Column(DateTime(timezone=True), nullable=True)
    brand_context_status = Column(String, nullable=True)
    brand_context_last_error = Column(Text, nullable=True)
    brand_context_job_id = Column(String, nullable=True)
    
    # Strategic Intelligence (extracted from brand context)
    strategic_intelligence = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    strategic_intelligence_updated_at = Column(DateTime(timezone=True), nullable=True)

    # -----------------------------------------------------------------------------
    # Plan change scheduling (DB is the source of truth)
    # -----------------------------------------------------------------------------
    # Used for scheduled downgrades/cancellations that become effective at a future time
    # (e.g., end of current paid cycle). The UI can show banners using these fields.
    pending_plan_name = Column(String, nullable=True)
    pending_plan_effective_at = Column(DateTime(timezone=True), nullable=True)
    last_plan_change_type = Column(String, nullable=True)  # upgrade|downgrade|cancel|none
    last_plan_change_at = Column(DateTime(timezone=True), nullable=True)
    last_shopify_subscription_status = Column(String, nullable=True)

class UsageRecord(Base):
    __tablename__ = "usage_records"

    # Composite Primary Key: user_id + billing_cycle_start
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True) 
    billing_cycle_start = Column(Date, primary_key=True) 
    
    # Deprecated column name in DB: token_count. Python attr is usage_count.
    usage_count = Column("token_count", BigInteger, default=0)
    last_updated = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    # Relationship back to the User
    user = relationship("User", back_populates="usage_records")

class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True) # e.g., "Basic", "Standard", "Pro"
    price_usd_monthly = Column(Numeric(10, 2))
    
    # CORE QUOTA DEFINITIONS
    # Deprecated column name in DB: monthly_token_quota. Python attr is monthly_rewrite_limit.
    monthly_rewrite_limit = Column("monthly_token_quota", BigInteger)
    max_request_rate = Column(Integer)

    # NEW: unified pricing/feature-gating fields (backfilled by seed_db.py)
    # - product_limit: monthly product/sync limit (-1 = unlimited)
    # - max_locales: max locales per operation (-1 = unlimited)
    # - features_json: UI-facing bullet list stored as JSON string
    product_limit = Column(Integer, nullable=True)
    max_locales = Column(Integer, nullable=True)
    features_json = Column(Text, nullable=True)

    # Billing cycle type for usage semantics:
    # - "recurring": monthly reset / recurring bucket
    # - "lifetime": one-time bucket that never resets (e.g., Free plan lifetime credits)
    billing_cycle_type = Column(String, nullable=True)
    
    # FEATURE GATES
    can_access_live_currency = Column(Boolean, default=False)
    can_stream_responses = Column(Boolean, default=False)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    users = relationship("User", back_populates="plan")


class StoreContext(Base):
    __tablename__ = "store_context"

    id = Column(Integer, primary_key=True, index=True)
    # Use shop domain as the tenant identifier (matches Shop.domain)
    shop_id = Column(String, index=True, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536).with_variant(TextType, "sqlite"), nullable=False)
    metadata_json = Column("metadata", JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# -----------------------------------------------------------------------------
# Agentic Architecture Tables
# -----------------------------------------------------------------------------

class Mission(Base):
    """
    Tracks long-running agent missions for a product.
    
    A mission represents a complete product optimization workflow
    that may involve multiple agents. The state is persisted here
    to support resumption, SSE streaming, and audit trails.
    """
    __tablename__ = "missions"

    id = Column(String, primary_key=True)  # UUID
    shop_id = Column(String, ForeignKey("shops.domain"), index=True, nullable=False)
    product_id = Column(String, index=True, nullable=False)
    
    # Current mission status
    # Values: PENDING, IN_PROGRESS, WAITING_APPROVAL, COMPLETED, ERROR
    status = Column(String, nullable=False, default="PENDING")
    
    # Serialized MissionState (full snapshot for resumption)
    current_state = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    
    # Agent execution logs for debugging/audit
    logs = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    
    # Plan tier that was active when mission started (for routing)
    plan_tier = Column(String, nullable=True)
    
    # Error tracking
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class AgentCorrection(Base):
    """
    Stores user corrections to agent outputs for learning.
    
    When a user edits the AI-generated content, we store the diff
    so agents can learn from these corrections in future runs.
    The embedding enables semantic similarity search.
    """
    __tablename__ = "agent_corrections"

    id = Column(String, primary_key=True)  # UUID
    shop_id = Column(String, index=True, nullable=False)
    
    # Which agent produced the original output
    agent_role = Column(String, nullable=False)  # "Copywriter", "PriceScout", etc.
    
    # The original AI-generated output
    original_output = Column(Text, nullable=False)
    
    # What the user changed it to
    user_correction = Column(Text, nullable=False)
    
    # Embedding for semantic similarity search
    # Allows finding corrections relevant to similar products
    embedding = Column(Vector(1536).with_variant(TextType, "sqlite"), nullable=True)
    
    # Context about when/why this correction was made
    product_id = Column(String, index=True, nullable=True)
    context_metadata = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BrandEntity(Base):
    """
    Knowledge graph triplets for brand intelligence.
    
    Stores Subject -> Relation -> Object triplets extracted from brand text
    to enable recursive retrieval and entity-based context expansion.
    """
    __tablename__ = "brand_entities"
    
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(String, ForeignKey("shops.domain"), index=True, nullable=False)
    
    # Triplet: Subject -> Relation -> Object
    subject = Column(String, nullable=False)
    subject_type = Column(String, nullable=False)  # material, technique, region, etc.
    relation = Column(String, nullable=False)  # uses, originates_from, trained_in, etc.
    object = Column(String, nullable=False)
    object_type = Column(String, nullable=False)
    
    # Metadata
    confidence = Column(Numeric(3, 2), default=1.0)
    source_chunk_id = Column(Integer, ForeignKey("store_context.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

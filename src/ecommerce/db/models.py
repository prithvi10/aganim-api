"""
Ecommerce (Shopify) domain-specific DB models.

These tables are Shopify-specific and stay in the ecommerce service.
"""
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Boolean,
    Date, BigInteger, Numeric, Text, JSON,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, synonym
from sqlalchemy.sql import func
from src.shared.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan_id = Column(Integer, ForeignKey("plans.id"))

    plan = relationship("Plan", back_populates="users")
    usage_records = relationship("UsageRecord", back_populates="user")


class Shop(Base):
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, unique=True, index=True)
    access_token = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    monthly_rewrites_used = Column(Integer, nullable=False, default=0, server_default="0")
    lifetime_rewrites_remaining = Column(Integer, nullable=False, default=10, server_default="10")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    welcome_back_pending = Column(Boolean, nullable=False, default=False, server_default="0")
    access_expires_at = Column(DateTime(timezone=True), nullable=True)
    current_plan_name = Column(String, nullable=True)
    last_plan_name = Column(String, nullable=True)
    last_uninstalled_at = Column(DateTime(timezone=True), nullable=True)
    reset_anchor_date = Column(DateTime(timezone=True), nullable=True)
    next_reset_date = Column(DateTime(timezone=True), nullable=True)
    fair_use_last_notified_at = Column(DateTime(timezone=True), nullable=True)
    monthly_cost_accumulated = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    onboarding_step = Column(Integer, nullable=False, default=0, server_default="0")
    is_onboarding_finished = Column(Boolean, nullable=False, default=False, server_default="0")
    brand_context = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    brand_context_updated_at = Column(DateTime(timezone=True), nullable=True)
    brand_context_status = Column(String, nullable=True)
    brand_context_last_error = Column(Text, nullable=True)
    brand_context_job_id = Column(String, nullable=True)
    strategic_intelligence = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    strategic_intelligence_updated_at = Column(DateTime(timezone=True), nullable=True)
    pending_plan_name = Column(String, nullable=True)
    pending_plan_effective_at = Column(DateTime(timezone=True), nullable=True)
    last_plan_change_type = Column(String, nullable=True)
    last_plan_change_at = Column(DateTime(timezone=True), nullable=True)
    last_shopify_subscription_status = Column(String, nullable=True)
    meta_access_token = Column(String, nullable=True)
    meta_page_id = Column(String, nullable=True)
    price_guardrails = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    logo_url = Column(String, nullable=True)
    ui_language = Column(String(5), nullable=False, default="en", server_default="en")
    default_target_locale = Column(String(10), nullable=False, default="en", server_default="en")

    free_trial_expires_at = Column(DateTime(timezone=True), nullable=True)

    # --- Plan-gating usage counters (added for plan overhaul) ---
    lifetime_missions_remaining = Column(Integer, nullable=False, default=3, server_default="3")
    lifetime_image_credits_remaining = Column(Integer, nullable=False, default=5, server_default="5")
    monthly_missions_used = Column(Integer, nullable=False, default=0, server_default="0")
    monthly_image_generations_used = Column(Integer, nullable=False, default=0, server_default="0")

    brand_soul_enabled = Column(Boolean, nullable=False, default=True, server_default="1")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    billing_cycle_start = Column(Date, primary_key=True)
    usage_count = Column("token_count", BigInteger, default=0)
    last_updated = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User", back_populates="usage_records")


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    price_usd_monthly = Column(Numeric(10, 2))
    monthly_rewrite_limit = Column("monthly_token_quota", BigInteger)
    max_request_rate = Column(Integer)
    product_limit = Column(Integer, nullable=True)
    max_locales = Column(Integer, nullable=True)
    features_json = Column(Text, nullable=True)
    billing_cycle_type = Column(String, nullable=True)
    can_access_live_currency = Column(Boolean, default=False)
    can_stream_responses = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="plan")


class FeatureUsage(Base):
    """Aggregate per-feature usage counters per billing cycle (fast quota checks)."""
    __tablename__ = "feature_usage"

    id = Column(Integer, primary_key=True, index=True)
    shop_domain = Column(String, index=True, nullable=False)
    feature = Column(String, nullable=False)
    billing_cycle_start = Column(Date, nullable=False)
    usage_count = Column(Integer, default=0)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UsageEventLog(Base):
    """Append-only audit trail for every billable action (admin analytics)."""
    __tablename__ = "usage_event_log"

    id = Column(Integer, primary_key=True, index=True)
    shop_domain = Column(String, index=True, nullable=False)
    plan_name = Column(String, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    feature = Column(String, index=True, nullable=False)

    product_count = Column(Integer, default=0)
    image_count = Column(Integer, default=0)
    prompt_tokens = Column(BigInteger, default=0)
    completion_tokens = Column(BigInteger, default=0)
    reasoning_tokens = Column(BigInteger, default=0)
    total_tokens = Column(BigInteger, default=0)
    estimated_cost_usd = Column(Numeric(10, 6), default=0)

    product_id = Column(String, nullable=True)
    mission_id = Column(String, nullable=True)
    agent_name = Column(String, nullable=True)
    model_used = Column(String, nullable=True)
    action = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrandEntity(Base):
    __tablename__ = "brand_entities"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True, nullable=False)      # was shop_id

    # Backward-compat synonym
    shop_id = synonym("tenant_id")

    subject = Column(String, nullable=False)
    subject_type = Column(String, nullable=False)
    relation = Column(String, nullable=False)
    object = Column(String, nullable=False)
    object_type = Column(String, nullable=False)

    confidence = Column(Numeric(3, 2), default=1.0)
    source_chunk_id = Column(Integer, ForeignKey("context_chunks.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OutreachLog(Base):
    """Tracks outreach emails sent to merchants."""
    __tablename__ = "outreach_log"

    id = Column(Integer, primary_key=True, index=True)
    recipient_email = Column(String, nullable=False)
    recipient_shop = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String, default="sent")
    sent_at = Column(DateTime(timezone=True), server_default=func.now())


class ConcernLog(Base):
    """Tracks merchant concerns / support requests."""
    __tablename__ = "concern_log"

    id = Column(Integer, primary_key=True, index=True)
    shop_domain = Column(String, index=True, nullable=False)
    email = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String, default="open")
    admin_reply = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Re-export agentic_core models so callers can import everything from one place
# ---------------------------------------------------------------------------
from src.agentic_core.db.models import (  # noqa: F401,E402
    Mission,
    AgentCorrection,
    ContextChunk,
)

# Backward compat alias: old code may reference StoreContext
StoreContext = ContextChunk

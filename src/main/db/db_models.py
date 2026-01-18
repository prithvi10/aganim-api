from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Date, BigInteger, Numeric, Text
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
    # The date the merchant installed or last changed plans.
    reset_anchor_date = Column(DateTime(timezone=True), nullable=True)
    # Computed as reset_anchor_date + 30 days (self-healed forward as needed).
    next_reset_date = Column(DateTime(timezone=True), nullable=True)

    # -----------------------------------------------------------------------------
    # Internal fair-use monitoring (NEVER shown to merchant)
    # -----------------------------------------------------------------------------
    fair_use_last_notified_at = Column(DateTime(timezone=True), nullable=True)
    monthly_cost_accumulated = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")

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

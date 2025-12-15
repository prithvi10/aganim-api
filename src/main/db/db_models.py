from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Date, BigInteger, Numeric
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

class UsageRecord(Base):
    __tablename__ = "usage_records"

    # Composite Primary Key: user_id + billing_cycle_start
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True) 
    billing_cycle_start = Column(Date, primary_key=True) 
    
    token_count = Column(BigInteger, default=0)
    last_updated = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    # Relationship back to the User
    user = relationship("User", back_populates="usage_records")

class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True) # e.g., "Basic Agent", "Pro Agent"
    price_usd_monthly = Column(Numeric(10, 2))
    
    # CORE QUOTA DEFINITIONS
    monthly_token_quota = Column(BigInteger)
    max_request_rate = Column(Integer)
    
    # FEATURE GATES
    can_access_live_currency = Column(Boolean, default=False)
    can_stream_responses = Column(Boolean, default=False)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    users = relationship("User", back_populates="plan")

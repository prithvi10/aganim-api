"""
SuperAdmin merchant list & detail endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import (
    Shop, User, FeatureUsage, UsageEventLog, Mission,
)
from .auth import verify_admin_token

router = APIRouter(dependencies=[Depends(verify_admin_token)])

PAGE_SIZE = 25


def _resolve_plan_display(shop: Shop) -> str:
    """Derive a human-readable plan label from the shop's plan lifecycle fields."""
    if shop.current_plan_name:
        return shop.current_plan_name
    if shop.last_shopify_subscription_status == "CANCELLED" and shop.last_plan_name:
        return f"{shop.last_plan_name} (Cancelled)"
    if shop.pending_plan_name:
        return f"{shop.pending_plan_name} (Pending)"
    return "Free"


def _shop_to_summary(shop: Shop) -> dict:
    return {
        "id": shop.id,
        "domain": shop.domain,
        "current_plan_name": shop.current_plan_name,
        "plan_display": _resolve_plan_display(shop),
        "last_plan_name": shop.last_plan_name,
        "subscription_status": shop.last_shopify_subscription_status,
        "is_active": shop.is_active,
        "created_at": str(shop.created_at) if shop.created_at else None,
        "updated_at": str(shop.updated_at) if shop.updated_at else None,
        "monthly_rewrites_used": shop.monthly_rewrites_used or 0,
        "monthly_missions_used": shop.monthly_missions_used or 0,
        "monthly_image_generations_used": shop.monthly_image_generations_used or 0,
        "monthly_cost_accumulated": float(shop.monthly_cost_accumulated or 0),
        "onboarding_step": shop.onboarding_step,
        "is_onboarding_finished": shop.is_onboarding_finished,
    }


@router.get("/merchants")
async def list_merchants(
    search: str = Query("", description="Search by domain"),
    plan: str = Query("", description="Filter by plan name"),
    sort: str = Query("created_at", description="Sort field"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    q = db.query(Shop)

    if search:
        q = q.filter(Shop.domain.ilike(f"%{search}%"))
    if plan:
        q = q.filter(Shop.current_plan_name == plan)

    sort_col = getattr(Shop, sort, Shop.created_at)
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    total = q.count()
    shops = q.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()

    return {
        "merchants": [_shop_to_summary(s) for s in shops],
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
    }


@router.get("/merchants/{shop_domain}")
async def merchant_detail(shop_domain: str, db: Session = Depends(get_db)):
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Merchant not found")

    user = db.query(User).filter(User.username == shop_domain).first()

    feature_usage = (
        db.query(FeatureUsage)
        .filter(FeatureUsage.shop_domain == shop_domain)
        .order_by(FeatureUsage.billing_cycle_start.desc())
        .limit(50)
        .all()
    )

    recent_events = (
        db.query(UsageEventLog)
        .filter(UsageEventLog.shop_domain == shop_domain)
        .order_by(UsageEventLog.created_at.desc())
        .limit(50)
        .all()
    )

    missions = (
        db.query(Mission)
        .filter(Mission.tenant_id == shop_domain)
        .order_by(Mission.created_at.desc())
        .limit(50)
        .all()
    )

    return {
        "shop": {
            "id": shop.id,
            "domain": shop.domain,
            "current_plan_name": shop.current_plan_name,
            "plan_display": _resolve_plan_display(shop),
            "last_plan_name": shop.last_plan_name,
            "pending_plan_name": shop.pending_plan_name,
            "last_plan_change_type": shop.last_plan_change_type,
            "last_shopify_subscription_status": shop.last_shopify_subscription_status,
            "last_plan_change_at": str(shop.last_plan_change_at) if shop.last_plan_change_at else None,
            "is_active": shop.is_active,
            "created_at": str(shop.created_at) if shop.created_at else None,
            "updated_at": str(shop.updated_at) if shop.updated_at else None,
            "monthly_rewrites_used": shop.monthly_rewrites_used or 0,
            "lifetime_rewrites_remaining": shop.lifetime_rewrites_remaining or 0,
            "monthly_missions_used": shop.monthly_missions_used or 0,
            "lifetime_missions_remaining": shop.lifetime_missions_remaining or 0,
            "monthly_image_generations_used": shop.monthly_image_generations_used or 0,
            "lifetime_image_credits_remaining": shop.lifetime_image_credits_remaining or 0,
            "monthly_cost_accumulated": float(shop.monthly_cost_accumulated or 0),
            "onboarding_step": shop.onboarding_step,
            "is_onboarding_finished": shop.is_onboarding_finished,
            "brand_context_status": shop.brand_context_status,
            "ui_language": shop.ui_language,
            "default_target_locale": shop.default_target_locale,
            "logo_url": shop.logo_url,
            "reset_anchor_date": str(shop.reset_anchor_date) if shop.reset_anchor_date else None,
            "next_reset_date": str(shop.next_reset_date) if shop.next_reset_date else None,
        },
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": str(user.created_at) if user.created_at else None,
        } if user else None,
        "feature_usage": [
            {
                "feature": fu.feature,
                "billing_cycle_start": str(fu.billing_cycle_start),
                "usage_count": fu.usage_count,
            }
            for fu in feature_usage
        ],
        "recent_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "feature": e.feature,
                "total_tokens": int(e.total_tokens or 0),
                "estimated_cost_usd": float(e.estimated_cost_usd or 0),
                "model_used": e.model_used,
                "created_at": str(e.created_at) if e.created_at else None,
            }
            for e in recent_events
        ],
        "missions": [
            {
                "id": m.id,
                "resource_id": m.resource_id,
                "status": m.status,
                "tier": m.tier,
                "error_message": m.error_message,
                "created_at": str(m.created_at) if m.created_at else None,
                "completed_at": str(m.completed_at) if m.completed_at else None,
            }
            for m in missions
        ],
    }

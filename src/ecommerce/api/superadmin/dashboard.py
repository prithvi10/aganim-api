"""
SuperAdmin dashboard & metrics endpoints.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, case, cast, Date, Integer
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import Shop, Plan, UsageEventLog, FeatureUsage, Mission
from .auth import verify_admin_token

router = APIRouter(dependencies=[Depends(verify_admin_token)])


@router.get("/dashboard/overview")
async def dashboard_overview(db: Session = Depends(get_db)):
    total_merchants = db.query(func.count(Shop.id)).scalar() or 0

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    active_merchants = (
        db.query(func.count(Shop.id))
        .filter(Shop.updated_at >= thirty_days_ago, Shop.is_active == True)
        .scalar()
    ) or 0

    plan_breakdown = (
        db.query(Shop.current_plan_name, func.count(Shop.id))
        .group_by(Shop.current_plan_name)
        .all()
    )

    total_rewrites = (
        db.query(func.coalesce(func.sum(Shop.monthly_rewrites_used), 0)).scalar()
    )
    total_missions = db.query(func.count(Mission.id)).scalar() or 0
    total_image_gens = (
        db.query(func.coalesce(func.sum(Shop.monthly_image_generations_used), 0)).scalar()
    )
    total_cost = (
        db.query(func.coalesce(func.sum(UsageEventLog.estimated_cost_usd), 0)).scalar()
    )

    return {
        "total_merchants": total_merchants,
        "active_merchants_30d": active_merchants,
        "plan_breakdown": {name or "None": count for name, count in plan_breakdown},
        "total_rewrites": int(total_rewrites),
        "total_missions": total_missions,
        "total_image_generations": int(total_image_gens),
        "total_estimated_cost_usd": float(total_cost),
    }


@router.get("/dashboard/usage-timeseries")
async def usage_timeseries(
    period: str = Query("30d", pattern="^(7d|30d|90d)$"),
    db: Session = Depends(get_db),
):
    days = {"7d": 7, "30d": 30, "90d": 90}[period]
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            cast(UsageEventLog.created_at, Date).label("day"),
            UsageEventLog.feature,
            func.count(UsageEventLog.id).label("count"),
            func.coalesce(func.sum(UsageEventLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageEventLog.estimated_cost_usd), 0).label("cost"),
        )
        .filter(UsageEventLog.created_at >= since)
        .group_by("day", UsageEventLog.feature)
        .order_by("day")
        .all()
    )

    series: dict[str, list] = {}
    for day, feature, count, tokens, cost in rows:
        day_str = str(day)
        if day_str not in series:
            series[day_str] = []
        series[day_str].append({
            "feature": feature,
            "count": count,
            "tokens": int(tokens),
            "cost": float(cost),
        })

    return {"period": period, "series": series}


@router.get("/dashboard/token-usage")
async def token_usage(db: Session = Depends(get_db)):
    rows = (
        db.query(
            UsageEventLog.shop_domain,
            func.coalesce(func.sum(UsageEventLog.prompt_tokens), 0).label("prompt"),
            func.coalesce(func.sum(UsageEventLog.completion_tokens), 0).label("completion"),
            func.coalesce(func.sum(UsageEventLog.reasoning_tokens), 0).label("reasoning"),
            func.coalesce(func.sum(UsageEventLog.total_tokens), 0).label("total"),
            func.coalesce(func.sum(UsageEventLog.estimated_cost_usd), 0).label("cost"),
        )
        .group_by(UsageEventLog.shop_domain)
        .order_by(func.sum(UsageEventLog.total_tokens).desc())
        .all()
    )

    return [
        {
            "shop_domain": r.shop_domain,
            "prompt_tokens": int(r.prompt),
            "completion_tokens": int(r.completion),
            "reasoning_tokens": int(r.reasoning),
            "total_tokens": int(r.total),
            "estimated_cost_usd": float(r.cost),
        }
        for r in rows
    ]


@router.get("/dashboard/image-credits")
async def image_credits(db: Session = Depends(get_db)):
    rows = (
        db.query(
            Shop.domain,
            Shop.current_plan_name,
            Shop.monthly_image_generations_used,
            Shop.lifetime_image_credits_remaining,
        )
        .order_by(Shop.monthly_image_generations_used.desc())
        .all()
    )

    return [
        {
            "shop_domain": r.domain,
            "plan": r.current_plan_name,
            "monthly_used": r.monthly_image_generations_used or 0,
            "lifetime_remaining": r.lifetime_image_credits_remaining or 0,
        }
        for r in rows
    ]


@router.get("/dashboard/plan-stats")
async def plan_stats(db: Session = Depends(get_db)):
    enrollment = (
        db.query(Shop.current_plan_name, func.count(Shop.id))
        .group_by(Shop.current_plan_name)
        .all()
    )

    recent_changes = (
        db.query(
            Shop.domain,
            Shop.last_plan_name,
            Shop.current_plan_name,
            Shop.last_plan_change_type,
            Shop.last_plan_change_at,
        )
        .filter(Shop.last_plan_change_at.isnot(None))
        .order_by(Shop.last_plan_change_at.desc())
        .limit(50)
        .all()
    )

    churned = (
        db.query(func.count(Shop.id))
        .filter(Shop.is_active == False)
        .scalar()
    ) or 0

    return {
        "enrollment": {name or "None": count for name, count in enrollment},
        "recent_changes": [
            {
                "shop_domain": r.domain,
                "from_plan": r.last_plan_name,
                "to_plan": r.current_plan_name,
                "change_type": r.last_plan_change_type,
                "changed_at": str(r.last_plan_change_at) if r.last_plan_change_at else None,
            }
            for r in recent_changes
        ],
        "churned_count": churned,
    }


@router.get("/dashboard/feature-usage")
async def feature_usage(db: Session = Depends(get_db)):
    rows = (
        db.query(
            FeatureUsage.feature,
            func.sum(FeatureUsage.usage_count).label("total"),
            func.count(func.distinct(FeatureUsage.shop_domain)).label("unique_shops"),
        )
        .group_by(FeatureUsage.feature)
        .order_by(func.sum(FeatureUsage.usage_count).desc())
        .all()
    )

    return [
        {
            "feature": r.feature,
            "total_usage": int(r.total),
            "unique_shops": int(r.unique_shops),
        }
        for r in rows
    ]

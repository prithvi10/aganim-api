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
from src.ecommerce.plans.entitlements import PLAN_ENTITLEMENTS
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
        "plan_breakdown": {name or "No Active Plan": count for name, count in plan_breakdown},
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
        "enrollment": {name or "No Active Plan": count for name, count in enrollment},
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


@router.get("/dashboard/revenue")
async def revenue_breakdown(db: Session = Depends(get_db)):
    """Monthly revenue based on active paid plan subscriptions, broken down by plan."""
    plan_prices: dict[str, float] = {}
    for plan in db.query(Plan).all():
        if plan.price_usd_monthly and float(plan.price_usd_monthly) > 0:
            plan_prices[plan.name] = float(plan.price_usd_monthly)

    paid_plans = list(plan_prices.keys())
    if not paid_plans:
        return {"total_mrr": 0, "by_plan": {}, "merchants": []}

    shops = (
        db.query(Shop.domain, Shop.current_plan_name)
        .filter(Shop.is_active == True, Shop.current_plan_name.in_(paid_plans))
        .all()
    )

    by_plan: dict[str, dict] = {}
    merchants: list[dict] = []
    total_mrr = 0.0

    for domain, plan_name in shops:
        price = plan_prices.get(plan_name, 0)
        total_mrr += price
        if plan_name not in by_plan:
            by_plan[plan_name] = {"count": 0, "revenue": 0.0}
        by_plan[plan_name]["count"] += 1
        by_plan[plan_name]["revenue"] += price
        merchants.append({"domain": domain, "plan": plan_name, "revenue": price})

    return {
        "total_mrr": round(total_mrr, 2),
        "by_plan": {k: {"count": v["count"], "revenue": round(v["revenue"], 2)} for k, v in by_plan.items()},
        "merchants": merchants,
    }


@router.get("/dashboard/attrition")
async def attrition_stats(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Merchants who left (uninstalled or cancelled paid plan) within the given period."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    plan_prices: dict[str, float] = {}
    for plan in db.query(Plan).all():
        if plan.price_usd_monthly and float(plan.price_usd_monthly) > 0:
            plan_prices[plan.name] = float(plan.price_usd_monthly)

    churned = (
        db.query(Shop)
        .filter(
            Shop.is_active == False,
            Shop.last_uninstalled_at >= since,
        )
        .order_by(Shop.last_uninstalled_at.desc())
        .all()
    )

    cancelled = (
        db.query(Shop)
        .filter(
            Shop.is_active == True,
            Shop.last_shopify_subscription_status == "CANCELLED",
            Shop.last_plan_change_at >= since,
            Shop.last_plan_name.isnot(None),
        )
        .order_by(Shop.last_plan_change_at.desc())
        .all()
    )

    merchants: list[dict] = []
    total_lost_revenue = 0.0
    plan_lost: dict[str, dict] = {}

    for shop in churned:
        plan = shop.last_plan_name or shop.current_plan_name or "Free"
        price = plan_prices.get(plan, 0)
        total_lost_revenue += price
        plan_lost.setdefault(plan, {"count": 0, "revenue": 0.0})
        plan_lost[plan]["count"] += 1
        plan_lost[plan]["revenue"] += price
        merchants.append({
            "domain": shop.domain,
            "type": "uninstalled",
            "last_plan": plan,
            "lost_revenue": price,
            "date": str(shop.last_uninstalled_at)[:10] if shop.last_uninstalled_at else None,
        })

    churned_ids = {s.id for s in churned}
    for shop in cancelled:
        if shop.id in churned_ids:
            continue
        plan = shop.last_plan_name or "Free"
        price = plan_prices.get(plan, 0)
        total_lost_revenue += price
        plan_lost.setdefault(plan, {"count": 0, "revenue": 0.0})
        plan_lost[plan]["count"] += 1
        plan_lost[plan]["revenue"] += price
        merchants.append({
            "domain": shop.domain,
            "type": "cancelled",
            "last_plan": plan,
            "lost_revenue": price,
            "date": str(shop.last_plan_change_at)[:10] if shop.last_plan_change_at else None,
        })

    return {
        "period_days": days,
        "total_churned": len(merchants),
        "total_lost_revenue": round(total_lost_revenue, 2),
        "by_plan": {k: {"count": v["count"], "revenue": round(v["revenue"], 2)} for k, v in plan_lost.items()},
        "merchants": merchants,
    }


THRESHOLD_PCT = 80


@router.get("/dashboard/approaching-limits")
async def approaching_limits(
    threshold: int = Query(THRESHOLD_PCT, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Return merchants whose usage is at or above *threshold*% of any plan limit."""
    shops = db.query(Shop).filter(Shop.is_active == True).all()

    rewrite_limits: dict[str, int] = {}
    for plan in db.query(Plan).all():
        if plan.monthly_rewrite_limit and plan.monthly_rewrite_limit > 0:
            rewrite_limits[plan.name] = int(plan.monthly_rewrite_limit)

    alerts: list[dict] = []

    for shop in shops:
        plan_name = shop.current_plan_name or "Free"
        ent = PLAN_ENTITLEMENTS.get(plan_name, PLAN_ENTITLEMENTS["Free"])
        breaches: list[dict] = []

        is_lifetime = ent.get("mission_limit_type") == "lifetime"

        if is_lifetime:
            lr = shop.lifetime_rewrites_remaining or 0
            if lr <= 2:
                breaches.append({
                    "resource": "Rewrites",
                    "used": 10 - lr,
                    "limit": 10,
                    "remaining": lr,
                    "pct": round((10 - lr) / 10 * 100) if lr < 10 else 0,
                    "limit_type": "lifetime",
                })
            lm = shop.lifetime_missions_remaining or 0
            m_limit = ent.get("mission_limit", 3)
            if m_limit > 0 and lm <= max(1, int(m_limit * (1 - threshold / 100))):
                breaches.append({
                    "resource": "Missions",
                    "used": m_limit - lm,
                    "limit": m_limit,
                    "remaining": lm,
                    "pct": round((m_limit - lm) / m_limit * 100) if m_limit > 0 else 0,
                    "limit_type": "lifetime",
                })
            li = shop.lifetime_image_credits_remaining or 0
            i_limit = ent.get("image_generation_limit", 5)
            if i_limit > 0 and li <= max(1, int(i_limit * (1 - threshold / 100))):
                breaches.append({
                    "resource": "Image Credits",
                    "used": i_limit - li,
                    "limit": i_limit,
                    "remaining": li,
                    "pct": round((i_limit - li) / i_limit * 100) if i_limit > 0 else 0,
                    "limit_type": "lifetime",
                })
        else:
            rw_limit = rewrite_limits.get(plan_name, 0)
            rw_used = shop.monthly_rewrites_used or 0
            if rw_limit > 0 and rw_used >= rw_limit * threshold / 100:
                breaches.append({
                    "resource": "Rewrites",
                    "used": rw_used,
                    "limit": rw_limit,
                    "remaining": max(0, rw_limit - rw_used),
                    "pct": min(100, round(rw_used / rw_limit * 100)),
                    "limit_type": "monthly",
                })
            m_limit = ent.get("mission_limit", 0)
            m_used = shop.monthly_missions_used or 0
            if m_limit > 0 and m_used >= m_limit * threshold / 100:
                breaches.append({
                    "resource": "Missions",
                    "used": m_used,
                    "limit": m_limit,
                    "remaining": max(0, m_limit - m_used),
                    "pct": min(100, round(m_used / m_limit * 100)),
                    "limit_type": "monthly",
                })
            i_limit = ent.get("image_generation_limit", 0)
            i_used = shop.monthly_image_generations_used or 0
            if i_limit > 0 and i_used >= i_limit * threshold / 100:
                breaches.append({
                    "resource": "Image Credits",
                    "used": i_used,
                    "limit": i_limit,
                    "remaining": max(0, i_limit - i_used),
                    "pct": min(100, round(i_used / i_limit * 100)),
                    "limit_type": "monthly",
                })

        if breaches:
            alerts.append({
                "domain": shop.domain,
                "plan": plan_name,
                "next_reset": str(shop.next_reset_date) if shop.next_reset_date else None,
                "breaches": breaches,
            })

    alerts.sort(key=lambda a: max(b["pct"] for b in a["breaches"]), reverse=True)
    return {"threshold": threshold, "merchants": alerts}

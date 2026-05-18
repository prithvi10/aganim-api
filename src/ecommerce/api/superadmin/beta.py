"""
SuperAdmin Beta Test endpoints — manage closed beta program.

Includes:
- Beta dashboard (KPIs, funnel)
- Merchant enrollment CRUD (enroll, update, remove)
- Per-merchant metrics (from usage_event_log)
- Beta-specific email sending (invite, check-in, feedback, exit)
- Feedback aggregation
"""
from __future__ import annotations

import asyncio
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func as sa_func, case, distinct
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import (
    BetaEnrollment, Shop, User, UsageEventLog, OutreachLog,
)
from src.ecommerce.services.email_service import send_email
from src.ecommerce.services.email_templates import (
    beta_invite_email,
    beta_welcome_email,
    beta_checkin_email,
    beta_feedback_request_email,
    beta_exit_email,
)
from .auth import verify_admin_token
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

import os as _os

router = APIRouter(prefix="/beta", dependencies=[Depends(verify_admin_token)])

VALID_STATUSES = {"invited", "accepted", "active", "completed", "churned"}
_UI_BASE_URL = _os.getenv("PUBLIC_SITE_URL", "https://aganim-ai.com")


# ── Request models ────────────────────────────────────────────────

class EnrollRequest(BaseModel):
    upgrade_plan: Optional[str] = "Pro"
    beta_duration_days: Optional[int] = 42
    source: Optional[str] = None
    target_market: Optional[str] = None
    notes: Optional[str] = None


class UpdateBetaMerchantRequest(BaseModel):
    status: Optional[str] = None
    feedback_score: Optional[float] = None
    willingness_to_pay: Optional[str] = None
    testimonial_text: Optional[str] = None
    notes: Optional[str] = None
    target_market: Optional[str] = None
    source: Optional[str] = None


class BetaInviteRequest(BaseModel):
    shop_domains: list[str] = []
    raw_emails: list[str] = []


class BetaEmailRequest(BaseModel):
    template: str = "checkin"
    status_filter: Optional[str] = None
    days_since_active: Optional[int] = None


# ── Helpers ───────────────────────────────────────────────────────

def _get_email_for_shop(db: Session, shop_domain: str) -> Optional[str]:
    user = db.query(User).filter(User.username == shop_domain).first()
    return user.email if user and user.email else None


def _get_beta_merchants_query(db: Session, status_filter: Optional[str] = None):
    q = db.query(BetaEnrollment)
    if status_filter and status_filter in VALID_STATUSES:
        q = q.filter(BetaEnrollment.status == status_filter)
    return q


# ── GET /beta/dashboard ───────────────────────────────────────────

@router.get("/dashboard")
async def beta_dashboard(db: Session = Depends(get_db)):
    total = db.query(sa_func.count(BetaEnrollment.id)).scalar() or 0
    active = db.query(sa_func.count(BetaEnrollment.id)).filter(
        BetaEnrollment.status == "active"
    ).scalar() or 0
    completed = db.query(sa_func.count(BetaEnrollment.id)).filter(
        BetaEnrollment.status == "completed"
    ).scalar() or 0
    churned = db.query(sa_func.count(BetaEnrollment.id)).filter(
        BetaEnrollment.status == "churned"
    ).scalar() or 0

    avg_feedback = db.query(sa_func.avg(BetaEnrollment.feedback_score)).filter(
        BetaEnrollment.feedback_score.isnot(None)
    ).scalar()

    wtp_yes = db.query(sa_func.count(BetaEnrollment.id)).filter(
        BetaEnrollment.willingness_to_pay == "yes"
    ).scalar() or 0
    wtp_total = db.query(sa_func.count(BetaEnrollment.id)).filter(
        BetaEnrollment.willingness_to_pay.isnot(None)
    ).scalar() or 0

    return {
        "total_enrolled": total,
        "active": active,
        "completed": completed,
        "churned": churned,
        "avg_feedback_score": float(avg_feedback) if avg_feedback else None,
        "willingness_to_pay_pct": round(wtp_yes / wtp_total * 100, 1) if wtp_total > 0 else None,
        "churn_rate_pct": round(churned / total * 100, 1) if total > 0 else 0,
    }


# ── GET /beta/funnel ──────────────────────────────────────────────

@router.get("/funnel")
async def beta_funnel(db: Session = Depends(get_db)):
    statuses = ["invited", "accepted", "active", "completed", "churned"]
    counts = {}
    for s in statuses:
        counts[s] = db.query(sa_func.count(BetaEnrollment.id)).filter(
            BetaEnrollment.status == s
        ).scalar() or 0
    return {"funnel": counts}


# ── GET /beta/merchants ───────────────────────────────────────────

@router.get("/merchants")
async def list_beta_merchants(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = _get_beta_merchants_query(db, status)
    total = q.count()
    enrollments = (
        q.order_by(BetaEnrollment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    merchants = []
    for e in enrollments:
        shop = db.query(Shop).filter(Shop.domain == e.shop_domain).first()
        last_event = (
            db.query(sa_func.max(UsageEventLog.created_at))
            .filter(UsageEventLog.shop_domain == e.shop_domain)
            .scalar()
        )
        total_rewrites = (
            db.query(sa_func.count(UsageEventLog.id))
            .filter(
                UsageEventLog.shop_domain == e.shop_domain,
                UsageEventLog.feature == "rewriter",
            )
            .scalar() or 0
        )
        features_used = (
            db.query(sa_func.count(distinct(UsageEventLog.feature)))
            .filter(UsageEventLog.shop_domain == e.shop_domain)
            .scalar() or 0
        )

        merchants.append({
            "shop_domain": e.shop_domain,
            "status": e.status,
            "plan": shop.current_plan_name if shop else None,
            "enrolled_at": str(e.created_at) if e.created_at else None,
            "last_active": str(last_event) if last_event else None,
            "beta_expires_at": str(shop.access_expires_at) if shop and shop.access_expires_at else None,
            "rewrites": total_rewrites,
            "features_used": features_used,
            "feedback_score": float(e.feedback_score) if e.feedback_score else None,
            "source": e.source,
            "signup_url": f"{_UI_BASE_URL}/beta/signup?token={e.invite_token}" if e.invite_token else None,
        })

    return {"merchants": merchants, "total": total, "page": page}


# ── GET /beta/merchants/{domain} ─────────────────────────────────

@router.get("/merchants/{domain}")
async def get_beta_merchant(domain: str, db: Session = Depends(get_db)):
    enrollment = db.query(BetaEnrollment).filter(
        BetaEnrollment.shop_domain == domain
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Merchant not in beta program")

    shop = db.query(Shop).filter(Shop.domain == domain).first()

    return {
        "enrollment": {
            "id": enrollment.id,
            "shop_domain": enrollment.shop_domain,
            "status": enrollment.status,
            "invited_at": str(enrollment.invited_at) if enrollment.invited_at else None,
            "accepted_at": str(enrollment.accepted_at) if enrollment.accepted_at else None,
            "activated_at": str(enrollment.activated_at) if enrollment.activated_at else None,
            "completed_at": str(enrollment.completed_at) if enrollment.completed_at else None,
            "feedback_score": float(enrollment.feedback_score) if enrollment.feedback_score else None,
            "willingness_to_pay": enrollment.willingness_to_pay,
            "testimonial_text": enrollment.testimonial_text,
            "notes": enrollment.notes,
            "target_market": enrollment.target_market,
            "source": enrollment.source,
            "invite_token": enrollment.invite_token,
            "signup_url": f"{_UI_BASE_URL}/beta/signup?token={enrollment.invite_token}" if enrollment.invite_token else None,
            "store_name": enrollment.store_name,
            "contact_email": enrollment.contact_email,
            "purpose": enrollment.purpose,
            "product_category": enrollment.product_category,
            "target_markets": enrollment.target_markets,
            "created_at": str(enrollment.created_at) if enrollment.created_at else None,
        },
        "shop": {
            "domain": shop.domain,
            "plan": shop.current_plan_name,
            "is_active": shop.is_active,
            "created_at": str(shop.created_at) if shop.created_at else None,
            "access_expires_at": str(shop.access_expires_at) if shop.access_expires_at else None,
            "monthly_rewrites_used": shop.monthly_rewrites_used,
            "monthly_missions_used": shop.monthly_missions_used,
            "monthly_image_generations_used": shop.monthly_image_generations_used,
        } if shop else None,
    }


# ── POST /beta/merchants/{domain}/enroll ──────────────────────────

@router.post("/merchants/{domain}/enroll")
async def enroll_merchant(
    domain: str, req: EnrollRequest, db: Session = Depends(get_db)
):
    shop = db.query(Shop).filter(Shop.domain == domain).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    existing = db.query(BetaEnrollment).filter(
        BetaEnrollment.shop_domain == domain
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Merchant already enrolled in beta")

    now = datetime.now(timezone.utc)
    enrollment = BetaEnrollment(
        shop_domain=domain,
        status="active",
        invited_at=now,
        accepted_at=now,
        activated_at=now,
        source=req.source,
        target_market=req.target_market,
        notes=req.notes,
    )
    db.add(enrollment)

    shop.is_beta_tester = True
    if req.upgrade_plan:
        shop.current_plan_name = req.upgrade_plan
        shop.last_plan_name = req.upgrade_plan
        # Set access window for the beta duration (auto-downgrades after expiry)
        beta_expires = now + timedelta(days=req.beta_duration_days)
        shop.access_expires_at = beta_expires
        shop.pending_plan_name = "Free"
        shop.pending_plan_effective_at = beta_expires
        shop.last_plan_change_type = "beta_grant"
        shop.last_plan_change_at = now
        # Reset usage counters for a fresh start
        shop.monthly_rewrites_used = 0
        shop.monthly_missions_used = 0
        shop.monthly_image_generations_used = 0
        shop.reset_anchor_date = now
        shop.next_reset_date = now + timedelta(days=30)
        # Clear any free trial (they're now on Pro beta)
        shop.free_trial_expires_at = None

    db.commit()
    db.refresh(enrollment)

    logger.info("[Beta] Enrolled %s (plan=%s, expires=%s)", domain, req.upgrade_plan, beta_expires if req.upgrade_plan else "N/A")

    return {
        "message": f"Merchant {domain} enrolled in beta",
        "enrollment_id": enrollment.id,
        "status": enrollment.status,
        "plan": shop.current_plan_name,
        "beta_expires_at": str(shop.access_expires_at) if shop.access_expires_at else None,
        "beta_duration_days": req.beta_duration_days,
    }


# ── PUT /beta/merchants/{domain}/update ───────────────────────────

@router.put("/merchants/{domain}/update")
async def update_beta_merchant(
    domain: str, req: UpdateBetaMerchantRequest, db: Session = Depends(get_db)
):
    enrollment = db.query(BetaEnrollment).filter(
        BetaEnrollment.shop_domain == domain
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Merchant not in beta program")

    now = datetime.now(timezone.utc)

    if req.status is not None:
        if req.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}")
        enrollment.status = req.status
        if req.status == "accepted" and not enrollment.accepted_at:
            enrollment.accepted_at = now
        elif req.status == "active" and not enrollment.activated_at:
            enrollment.activated_at = now
        elif req.status == "completed" and not enrollment.completed_at:
            enrollment.completed_at = now

    if req.feedback_score is not None:
        enrollment.feedback_score = req.feedback_score
    if req.willingness_to_pay is not None:
        enrollment.willingness_to_pay = req.willingness_to_pay
    if req.testimonial_text is not None:
        enrollment.testimonial_text = req.testimonial_text
    if req.notes is not None:
        enrollment.notes = req.notes
    if req.target_market is not None:
        enrollment.target_market = req.target_market
    if req.source is not None:
        enrollment.source = req.source

    db.commit()
    return {"message": f"Beta enrollment for {domain} updated", "status": enrollment.status}


# ── POST /beta/merchants/{domain}/remove ──────────────────────────

@router.post("/merchants/{domain}/remove")
async def remove_beta_merchant(domain: str, db: Session = Depends(get_db)):
    enrollment = db.query(BetaEnrollment).filter(
        BetaEnrollment.shop_domain == domain
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Merchant not in beta program")

    enrollment.status = "churned"
    enrollment.completed_at = datetime.now(timezone.utc)

    shop = db.query(Shop).filter(Shop.domain == domain).first()
    if shop:
        shop.is_beta_tester = False
        shop.current_plan_name = "Free"

    db.commit()

    logger.info("[Beta] Removed %s from beta (downgraded to Free)", domain)
    return {"message": f"Merchant {domain} removed from beta", "status": "churned"}


# ── GET /beta/metrics/{domain} ────────────────────────────────────

@router.get("/metrics/{domain}")
async def beta_merchant_metrics(domain: str, db: Session = Depends(get_db)):
    enrollment = db.query(BetaEnrollment).filter(
        BetaEnrollment.shop_domain == domain
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Merchant not in beta program")

    total_events = (
        db.query(sa_func.count(UsageEventLog.id))
        .filter(UsageEventLog.shop_domain == domain)
        .scalar() or 0
    )
    total_rewrites = (
        db.query(sa_func.count(UsageEventLog.id))
        .filter(UsageEventLog.shop_domain == domain, UsageEventLog.feature == "rewriter")
        .scalar() or 0
    )
    total_missions = (
        db.query(sa_func.count(UsageEventLog.id))
        .filter(
            UsageEventLog.shop_domain == domain,
            UsageEventLog.feature == "rewriter",
            UsageEventLog.mission_id.isnot(None),
        )
        .scalar() or 0
    )
    total_images = (
        db.query(sa_func.count(UsageEventLog.id))
        .filter(UsageEventLog.shop_domain == domain, UsageEventLog.feature == "image_generation")
        .scalar() or 0
    )
    features_used = (
        db.query(distinct(UsageEventLog.feature))
        .filter(UsageEventLog.shop_domain == domain)
        .all()
    )
    last_active = (
        db.query(sa_func.max(UsageEventLog.created_at))
        .filter(UsageEventLog.shop_domain == domain)
        .scalar()
    )

    # Daily usage (last 30 days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    daily_usage = (
        db.query(
            sa_func.date(UsageEventLog.created_at).label("day"),
            sa_func.count(UsageEventLog.id).label("count"),
        )
        .filter(UsageEventLog.shop_domain == domain, UsageEventLog.created_at >= cutoff)
        .group_by(sa_func.date(UsageEventLog.created_at))
        .order_by(sa_func.date(UsageEventLog.created_at))
        .all()
    )

    return {
        "shop_domain": domain,
        "total_events": total_events,
        "rewrites": total_rewrites,
        "missions": total_missions,
        "images": total_images,
        "features_used": [f[0] for f in features_used],
        "last_active": str(last_active) if last_active else None,
        "daily_usage": [{"day": str(d.day), "count": d.count} for d in daily_usage],
    }


# ── GET /beta/feedback ────────────────────────────────────────────

@router.get("/feedback")
async def beta_feedback(db: Session = Depends(get_db)):
    enrollments_with_feedback = (
        db.query(BetaEnrollment)
        .filter(BetaEnrollment.feedback_score.isnot(None))
        .all()
    )

    scores = [float(e.feedback_score) for e in enrollments_with_feedback]
    wtp_counts = {"yes": 0, "maybe": 0, "no": 0}
    for e in db.query(BetaEnrollment).filter(
        BetaEnrollment.willingness_to_pay.isnot(None)
    ).all():
        wtp = e.willingness_to_pay.lower()
        if wtp in wtp_counts:
            wtp_counts[wtp] += 1

    testimonials = (
        db.query(BetaEnrollment)
        .filter(BetaEnrollment.testimonial_text.isnot(None))
        .all()
    )

    return {
        "total_responses": len(scores),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "score_distribution": {
            "1-2": sum(1 for s in scores if s <= 2),
            "3": sum(1 for s in scores if 2 < s <= 3),
            "4-5": sum(1 for s in scores if s > 3),
        },
        "willingness_to_pay": wtp_counts,
        "testimonials": [
            {"shop_domain": t.shop_domain, "text": t.testimonial_text}
            for t in testimonials
        ],
    }


# ── POST /beta/invite ─────────────────────────────────────────────

@router.post("/invite")
async def send_beta_invite(req: BetaInviteRequest, db: Session = Depends(get_db)):
    if not req.shop_domains and not req.raw_emails:
        raise HTTPException(status_code=400, detail="No recipients specified")

    now = datetime.now(timezone.utc)
    results: list[dict] = []

    for domain in req.shop_domains:
        email = _get_email_for_shop(db, domain)
        if not email:
            results.append({"domain": domain, "status": "skipped", "reason": "no email"})
            continue

        # Generate token and create enrollment record if not exists
        existing = db.query(BetaEnrollment).filter(
            BetaEnrollment.shop_domain == domain
        ).first()
        if existing and existing.status != "churned":
            token = existing.invite_token or _uuid.uuid4().hex
            existing.invite_token = token
        else:
            token = _uuid.uuid4().hex
            enrollment = BetaEnrollment(
                shop_domain=domain,
                status="invited",
                invite_token=token,
                invited_at=now,
                source="admin_invite",
            )
            db.add(enrollment)

        # Flush to validate unique constraints before sending email
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            results.append({"domain": domain, "status": "skipped", "reason": "already_enrolled"})
            continue

        signup_url = f"{_UI_BASE_URL}/beta/signup?token={token}"
        subject, html_body, text_body = beta_invite_email(domain, signup_url=signup_url)
        try:
            await send_email(to=email, subject=subject, html_body=html_body, text_body=text_body)
            status = "sent"
        except Exception as exc:
            logger.error("[Beta] invite failed for %s: %s", email, exc)
            status = "failed"

        log = OutreachLog(
            recipient_email=email, recipient_shop=domain,
            subject=subject, body=text_body[:500], status=status,
        )
        db.add(log)
        results.append({"domain": domain, "email": email, "status": status, "signup_url": signup_url})

        if len(req.shop_domains) > 1:
            await asyncio.sleep(1.0)

    for email in req.raw_emails:
        # For raw emails, use email as placeholder domain
        placeholder_domain = email.split("@")[0] + ".myshopify.com"
        existing = db.query(BetaEnrollment).filter(
            BetaEnrollment.shop_domain == placeholder_domain
        ).first()
        if existing and existing.status != "churned":
            token = existing.invite_token or _uuid.uuid4().hex
            existing.invite_token = token
            existing.contact_email = email
        else:
            token = _uuid.uuid4().hex
            enrollment = BetaEnrollment(
                shop_domain=placeholder_domain,
                status="invited",
                invite_token=token,
                invited_at=now,
                contact_email=email,
                source="admin_invite",
            )
            db.add(enrollment)

        # Flush to validate unique constraints before sending email
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            results.append({"email": email, "status": "skipped", "reason": "already_enrolled"})
            continue

        signup_url = f"{_UI_BASE_URL}/beta/signup?token={token}"
        subject, html_body, text_body = beta_invite_email(email, signup_url=signup_url)
        try:
            await send_email(to=email, subject=subject, html_body=html_body, text_body=text_body)
            status = "sent"
        except Exception as exc:
            logger.error("[Beta] invite failed for %s: %s", email, exc)
            status = "failed"

        log = OutreachLog(
            recipient_email=email, recipient_shop=None,
            subject=subject, body=text_body[:500], status=status,
        )
        db.add(log)
        results.append({"email": email, "status": status, "signup_url": signup_url})

        if len(req.raw_emails) > 1:
            await asyncio.sleep(1.0)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="One or more merchants are already enrolled in the beta program",
        )

    sent = sum(1 for r in results if r["status"] == "sent")
    return {
        "message": f"Beta invite sent to {sent}/{len(results)} recipient(s)",
        "total": len(results),
        "sent": sent,
        "details": results,
    }


# ── POST /beta/email/send ─────────────────────────────────────────

@router.post("/email/send")
async def send_beta_email(req: BetaEmailRequest, db: Session = Depends(get_db)):
    q = db.query(BetaEnrollment)
    if req.status_filter and req.status_filter in VALID_STATUSES:
        q = q.filter(BetaEnrollment.status == req.status_filter)

    enrollments = q.all()
    if not enrollments:
        raise HTTPException(status_code=400, detail="No beta merchants match the filter")

    template_map = {
        "invite": beta_invite_email,
        "welcome": beta_welcome_email,
        "checkin": beta_checkin_email,
        "feedback": beta_feedback_request_email,
        "exit": beta_exit_email,
    }
    template_fn = template_map.get(req.template)
    if not template_fn:
        raise HTTPException(status_code=400, detail=f"Unknown beta template: {req.template}")

    _FEEDBACK_TEMPLATES = {"checkin", "feedback", "exit"}

    results: list[dict] = []
    for idx, enrollment in enumerate(enrollments):
        email = _get_email_for_shop(db, enrollment.shop_domain)
        if not email:
            results.append({"domain": enrollment.shop_domain, "status": "skipped"})
            continue

        if req.template in _FEEDBACK_TEMPLATES and enrollment.invite_token:
            feedback_url = f"{_UI_BASE_URL}/beta/feedback?token={enrollment.invite_token}"
            subject, html_body, text_body = template_fn(enrollment.shop_domain, feedback_url=feedback_url)
        else:
            subject, html_body, text_body = template_fn(enrollment.shop_domain)
        try:
            await send_email(to=email, subject=subject, html_body=html_body, text_body=text_body)
            status = "sent"
        except Exception as exc:
            logger.error("[Beta] %s email failed for %s: %s", req.template, email, exc)
            status = "failed"

        log = OutreachLog(
            recipient_email=email, recipient_shop=enrollment.shop_domain,
            subject=subject, body=text_body[:500], status=status,
        )
        db.add(log)
        results.append({"domain": enrollment.shop_domain, "email": email, "status": status})

        if idx < len(enrollments) - 1:
            await asyncio.sleep(1.0)

    db.commit()

    sent = sum(1 for r in results if r["status"] == "sent")
    return {
        "message": f"Beta {req.template} email sent to {sent}/{len(results)} merchant(s)",
        "template": req.template,
        "total": len(results),
        "sent": sent,
    }


# ── GET /beta/email/templates ─────────────────────────────────────

@router.get("/email/templates")
async def list_beta_email_templates():
    return {
        "templates": [
            {"id": "invite", "name": "Beta Invite", "description": "Cold outreach to prospective merchants"},
            {"id": "welcome", "name": "Beta Welcome", "description": "Sent when merchant accepts / installs"},
            {"id": "checkin", "name": "Beta Check-in", "description": "Weekly engagement nudge with usage stats"},
            {"id": "feedback", "name": "Beta Feedback Request", "description": "Structured feedback collection"},
            {"id": "exit", "name": "Beta Exit / Thank You", "description": "Sent at end of beta period"},
        ]
    }

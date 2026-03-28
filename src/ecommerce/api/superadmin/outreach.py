"""
SuperAdmin outreach endpoints — SES email integration.

Includes:
- Legacy send/send-template endpoints
- Admin email composer endpoints (send-custom, send-feedback, send-rating)
- Rate-limited bulk sending with 1 s delay between emails
- Recipient filtering (all_active, pro_only, installed_14d_ago)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import OutreachLog, Shop, User
from src.ecommerce.services.email_service import (
    send_email,
    send_bulk_email,
    send_rate_limited_bulk_email,
)
from src.ecommerce.services.email_templates import (
    TEMPLATE_REGISTRY,
    generate_base_email_template,
    welcome_email,
    plan_upgrade_email,
    credit_limit_reached_email,
    enterprise_invite_email,
    feedback_email,
    rating_email,
    custom_admin_email,
)
from .auth import verify_admin_token
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(verify_admin_token)])


# ── Enums & request models ─────────────────────────────────────────

class TemplateName(str, Enum):
    welcome = "welcome"
    upgrade = "upgrade"
    credit_limit = "credit_limit"
    enterprise = "enterprise"
    feedback = "feedback"
    rating = "rating"
    custom = "custom"


class RecipientFilter(str, Enum):
    all_active = "all_active"
    pro_only = "pro_only"
    installed_14d_ago = "installed_14d_ago"


class SendEmailRequest(BaseModel):
    to_emails: list[str] = []
    merchant_domains: list[str] = []
    subject: str
    body: str
    template: Optional[TemplateName] = None


class SendTemplateRequest(BaseModel):
    template: TemplateName
    merchant_domain: str
    extra_params: dict = {}


class SendCustomEmailRequest(BaseModel):
    recipient_filter: RecipientFilter
    subject: str
    html_body: str


class SendFeedbackRequest(BaseModel):
    recipient_filter: RecipientFilter
    feedback_link: str = "https://forms.gle/aganim-feedback"


class SendRatingRequest(BaseModel):
    recipient_filter: RecipientFilter
    app_store_review_link: str = "https://apps.shopify.com/aganim#reviews"


class SendTemplateBulkRequest(BaseModel):
    template: TemplateName
    recipient_filter: RecipientFilter
    app_url: str = ""
    plan_name: str = ""
    upgrade_url: str = ""
    feedback_link: str = ""
    app_store_review_link: str = ""
    subject: str = ""
    html_body: str = ""


# ── Recipient resolution ───────────────────────────────────────────

def _get_email_for_shop(db: Session, shop_domain: str) -> str:
    """Look up the merchant's real email from the User table, fall back to domain."""
    user = db.query(User).filter(User.username == shop_domain).first()
    return user.email if user and user.email else shop_domain


def _resolve_recipients(
    db: Session, recipient_filter: RecipientFilter
) -> list[dict]:
    """
    Return a list of dicts with ``domain`` and ``email`` for each matching shop.
    Uses ``User.email`` when available, falls back to ``Shop.domain``.
    """
    q = db.query(Shop).filter(Shop.is_active == True)  # noqa: E712

    if recipient_filter == RecipientFilter.pro_only:
        q = q.filter(Shop.current_plan_name == "Pro")
    elif recipient_filter == RecipientFilter.installed_14d_ago:
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        q = q.filter(Shop.created_at <= cutoff)

    shops = q.all()

    results = []
    for shop in shops:
        email = _get_email_for_shop(db, shop.domain)
        results.append({"domain": shop.domain, "email": email})
    return results


# ── POST /outreach/send ────────────────────────────────────────────

@router.post("/outreach/send")
async def send_outreach(req: SendEmailRequest, db: Session = Depends(get_db)):
    recipients: list[dict] = []

    for email in req.to_emails:
        recipients.append({"email": email, "shop": None})

    if req.merchant_domains:
        shops = (
            db.query(Shop)
            .filter(Shop.domain.in_(req.merchant_domains))
            .all()
        )
        for shop in shops:
            email = _get_email_for_shop(db, shop.domain)
            recipients.append({"email": email, "shop": shop.domain})

    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients specified")

    html_body = f"<div>{req.body}</div>"
    text_body = req.body

    logs = []
    for r in recipients:
        status = "sent"
        try:
            await send_email(
                to=r["email"],
                subject=req.subject,
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as exc:
            logger.error("[Outreach] SES failed for %s: %s", r["email"], exc)
            status = "failed"

        log = OutreachLog(
            recipient_email=r["email"],
            recipient_shop=r["shop"],
            subject=req.subject,
            body=req.body,
            status=status,
        )
        db.add(log)
        logs.append({"email": r["email"], "status": status})

    db.commit()

    sent = sum(1 for l in logs if l["status"] == "sent")
    failed = sum(1 for l in logs if l["status"] == "failed")

    logger.info(
        "[Outreach] send subject=%r total=%d sent=%d failed=%d",
        req.subject, len(logs), sent, failed,
    )

    return {
        "message": f"Email sent to {sent}/{len(logs)} recipient(s)",
        "recipients": len(logs),
        "sent": sent,
        "failed": failed,
        "details": logs,
    }


# ── POST /outreach/send-test-template ──────────────────────────────

class SendTestTemplateRequest(BaseModel):
    template: TemplateName
    to_email: str
    merchant_name: str = "Test Store"
    app_url: str = "https://app.aganim.com"
    plan_name: str = "Pro"
    upgrade_url: str = "https://app.aganim.com/pricing"
    feedback_link: str = "https://forms.gle/aganim-feedback"
    app_store_review_link: str = "https://apps.shopify.com/aganim#reviews"
    subject: str = ""
    html_body: str = ""


@router.post("/outreach/send-test-template")
async def send_test_template(req: SendTestTemplateRequest):
    """Render any template and send to a single test email address."""
    try:
        if req.template == TemplateName.welcome:
            subj, html, text = welcome_email(req.merchant_name, req.app_url)
        elif req.template == TemplateName.upgrade:
            subj, html, text = plan_upgrade_email(req.merchant_name, req.plan_name, req.app_url)
        elif req.template == TemplateName.credit_limit:
            subj, html, text = credit_limit_reached_email(req.merchant_name, req.plan_name, req.upgrade_url)
        elif req.template == TemplateName.enterprise:
            subj, html, text = enterprise_invite_email(req.merchant_name)
        elif req.template == TemplateName.feedback:
            subj, html, text = feedback_email(req.merchant_name, req.feedback_link)
        elif req.template == TemplateName.rating:
            subj, html, text = rating_email(req.merchant_name, req.app_store_review_link)
        elif req.template == TemplateName.custom:
            _, html, text = custom_admin_email(req.html_body or "<p>Test custom email</p>")
            subj = req.subject or "Test Custom Email"
        else:
            raise HTTPException(status_code=400, detail="Unknown template")
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f"Missing template params: {exc}")

    subj = f"[TEST] {subj}"

    try:
        result = await send_email(to=req.to_email, subject=subj, html_body=html, text_body=text)
        return {"status": "sent", "template": req.template.value, "recipient": req.to_email, **result}
    except Exception as exc:
        logger.error("[Outreach] test-template failed: %s", exc)
        return {"status": "failed", "template": req.template.value, "error": str(exc)}


# ── POST /outreach/send-template ───────────────────────────────────

@router.post("/outreach/send-template")
async def send_template_outreach(
    req: SendTemplateRequest, db: Session = Depends(get_db)
):
    shop = db.query(Shop).filter(Shop.domain == req.merchant_domain).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    template_fn = TEMPLATE_REGISTRY.get(req.template.value)
    if not template_fn:
        raise HTTPException(status_code=400, detail="Unknown template")

    merchant_name = req.extra_params.get("merchant_name", shop.domain)
    params = req.extra_params.copy()
    params["merchant_name"] = merchant_name

    try:
        if req.template == TemplateName.welcome:
            subject, html_body, text_body = template_fn(
                merchant_name=merchant_name,
                app_url=params.get("app_url", ""),
            )
        elif req.template == TemplateName.upgrade:
            subject, html_body, text_body = template_fn(
                merchant_name=merchant_name,
                plan_name=params.get("plan_name", shop.current_plan_name or "Basic"),
                app_url=params.get("app_url", ""),
            )
        elif req.template == TemplateName.credit_limit:
            subject, html_body, text_body = template_fn(
                merchant_name=merchant_name,
                plan_name=params.get("plan_name", shop.current_plan_name or "Free"),
                upgrade_url=params.get("upgrade_url", ""),
            )
        elif req.template == TemplateName.enterprise:
            subject, html_body, text_body = template_fn(
                merchant_name=merchant_name,
            )
        elif req.template == TemplateName.feedback:
            subject, html_body, text_body = template_fn(
                merchant_name=merchant_name,
                feedback_link=params.get("feedback_link", ""),
            )
        elif req.template == TemplateName.rating:
            subject, html_body, text_body = template_fn(
                merchant_name=merchant_name,
                app_store_review_link=params.get("app_store_review_link", ""),
            )
        elif req.template == TemplateName.custom:
            _, html_body, text_body = template_fn(
                custom_html_body=params.get("html_body", ""),
            )
            subject = params.get("subject", "Message from Aganim")
        else:
            raise HTTPException(status_code=400, detail="Unsupported template")
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f"Missing template params: {exc}")

    recipient_email = params.get("email") or _get_email_for_shop(db, shop.domain)

    try:
        result = await send_email(
            to=recipient_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )
        status = "sent"
    except Exception as exc:
        logger.error("[Outreach] template send failed: %s", exc)
        result = {"error": str(exc)}
        status = "failed"

    log = OutreachLog(
        recipient_email=recipient_email,
        recipient_shop=shop.domain,
        subject=subject,
        body=text_body,
        status=status,
    )
    db.add(log)
    db.commit()

    return {
        "status": status,
        "template": req.template.value,
        "recipient": recipient_email,
        **result,
    }


# ── POST /outreach/emails/send-custom ──────────────────────────────

@router.post("/outreach/emails/send-custom")
async def send_custom_email_endpoint(
    req: SendCustomEmailRequest, db: Session = Depends(get_db)
):
    """
    Send a custom HTML email to filtered merchants.  The HTML body is wrapped
    in the branded base template.  Emails are sent with a 1 s delay between
    each to stay within SES rate limits.
    """
    recipients = _resolve_recipients(db, req.recipient_filter)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients match the filter")

    _, html_body, text_body = custom_admin_email(req.html_body)

    recipient_emails = [r["email"] for r in recipients]
    results = await send_rate_limited_bulk_email(
        recipients=recipient_emails,
        subject=req.subject,
        html_body=html_body,
        text_body=text_body,
    )

    email_to_domain = {r["email"]: r["domain"] for r in recipients}
    for r in results:
        log = OutreachLog(
            recipient_email=r["email"],
            recipient_shop=email_to_domain.get(r["email"], r["email"]),
            subject=req.subject,
            body=text_body[:500],
            status=r["status"],
        )
        db.add(log)
    db.commit()

    sent = sum(1 for r in results if r["status"] == "sent")
    failed = sum(1 for r in results if r["status"] == "failed")

    return {
        "message": f"Custom email sent to {sent}/{len(results)} merchants",
        "total": len(results),
        "sent": sent,
        "failed": failed,
        "filter": req.recipient_filter.value,
    }


# ── POST /outreach/emails/send-feedback ────────────────────────────

@router.post("/outreach/emails/send-feedback")
async def send_feedback_email_endpoint(
    req: SendFeedbackRequest, db: Session = Depends(get_db)
):
    """Send the feedback request template to filtered merchants."""
    recipients = _resolve_recipients(db, req.recipient_filter)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients match the filter")

    results: list[dict] = []
    for idx, rcpt in enumerate(recipients):
        subject, html_body, text_body = feedback_email(
            merchant_name=rcpt["domain"],
            feedback_link=req.feedback_link,
        )
        try:
            resp = await send_email(
                to=rcpt["email"], subject=subject,
                html_body=html_body, text_body=text_body,
            )
            status = "sent"
        except Exception as exc:
            logger.error("[Outreach] feedback failed for %s: %s", rcpt["email"], exc)
            resp = {"error": str(exc)}
            status = "failed"

        results.append({"email": rcpt["email"], "status": status})
        log = OutreachLog(
            recipient_email=rcpt["email"], recipient_shop=rcpt["domain"],
            subject=subject, body=text_body[:500], status=status,
        )
        db.add(log)

        if idx < len(recipients) - 1:
            await asyncio.sleep(1.0)

    db.commit()

    sent = sum(1 for r in results if r["status"] == "sent")
    return {
        "message": f"Feedback email sent to {sent}/{len(results)} merchants",
        "total": len(results),
        "sent": sent,
        "failed": len(results) - sent,
        "filter": req.recipient_filter.value,
    }


# ── POST /outreach/emails/send-rating ──────────────────────────────

@router.post("/outreach/emails/send-rating")
async def send_rating_email_endpoint(
    req: SendRatingRequest, db: Session = Depends(get_db)
):
    """Send the app-store rating request template to filtered merchants."""
    recipients = _resolve_recipients(db, req.recipient_filter)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients match the filter")

    results: list[dict] = []
    for idx, rcpt in enumerate(recipients):
        subject, html_body, text_body = rating_email(
            merchant_name=rcpt["domain"],
            app_store_review_link=req.app_store_review_link,
        )
        try:
            resp = await send_email(
                to=rcpt["email"], subject=subject,
                html_body=html_body, text_body=text_body,
            )
            status = "sent"
        except Exception as exc:
            logger.error("[Outreach] rating failed for %s: %s", rcpt["email"], exc)
            resp = {"error": str(exc)}
            status = "failed"

        results.append({"email": rcpt["email"], "status": status})
        log = OutreachLog(
            recipient_email=rcpt["email"], recipient_shop=rcpt["domain"],
            subject=subject, body=text_body[:500], status=status,
        )
        db.add(log)

        if idx < len(recipients) - 1:
            await asyncio.sleep(1.0)

    db.commit()

    sent = sum(1 for r in results if r["status"] == "sent")
    return {
        "message": f"Rating email sent to {sent}/{len(results)} merchants",
        "total": len(results),
        "sent": sent,
        "failed": len(results) - sent,
        "filter": req.recipient_filter.value,
    }


# ── POST /outreach/emails/send-template-bulk ───────────────────────

@router.post("/outreach/emails/send-template-bulk")
async def send_template_bulk_endpoint(
    req: SendTemplateBulkRequest, db: Session = Depends(get_db)
):
    """Send any template to filtered merchants with rate-limiting."""
    recipients = _resolve_recipients(db, req.recipient_filter)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients match the filter")

    results: list[dict] = []
    for idx, rcpt in enumerate(recipients):
        merchant_name = rcpt["domain"]
        try:
            if req.template == TemplateName.welcome:
                subject, html_body, text_body = welcome_email(
                    merchant_name=merchant_name,
                    app_url=req.app_url or "https://app.aganim.com",
                )
            elif req.template == TemplateName.upgrade:
                subject, html_body, text_body = plan_upgrade_email(
                    merchant_name=merchant_name,
                    plan_name=req.plan_name or "Pro",
                    app_url=req.app_url or "https://app.aganim.com",
                )
            elif req.template == TemplateName.credit_limit:
                subject, html_body, text_body = credit_limit_reached_email(
                    merchant_name=merchant_name,
                    plan_name=req.plan_name or "Free",
                    upgrade_url=req.upgrade_url or "https://app.aganim.com/pricing",
                )
            elif req.template == TemplateName.enterprise:
                subject, html_body, text_body = enterprise_invite_email(
                    merchant_name=merchant_name,
                )
            elif req.template == TemplateName.feedback:
                subject, html_body, text_body = feedback_email(
                    merchant_name=merchant_name,
                    feedback_link=req.feedback_link,
                )
            elif req.template == TemplateName.rating:
                subject, html_body, text_body = rating_email(
                    merchant_name=merchant_name,
                    app_store_review_link=req.app_store_review_link,
                )
            elif req.template == TemplateName.custom:
                _, html_body, text_body = custom_admin_email(req.html_body)
                subject = req.subject or "Message from Aganim"
            else:
                raise HTTPException(status_code=400, detail="Unknown template")
        except TypeError as exc:
            raise HTTPException(status_code=400, detail=f"Missing template params: {exc}")

        try:
            resp = await send_email(
                to=rcpt["email"], subject=subject,
                html_body=html_body, text_body=text_body,
            )
            status = "sent"
        except Exception as exc:
            logger.error("[Outreach] %s failed for %s: %s", req.template.value, rcpt["email"], exc)
            resp = {"error": str(exc)}
            status = "failed"

        results.append({"email": rcpt["email"], "status": status})
        log = OutreachLog(
            recipient_email=rcpt["email"], recipient_shop=rcpt["domain"],
            subject=subject, body=text_body[:500], status=status,
        )
        db.add(log)

        if idx < len(recipients) - 1:
            await asyncio.sleep(1.0)

    db.commit()

    sent = sum(1 for r in results if r["status"] == "sent")
    return {
        "message": f"{req.template.value} email sent to {sent}/{len(results)} merchants",
        "total": len(results),
        "sent": sent,
        "failed": len(results) - sent,
        "filter": req.recipient_filter.value,
        "template": req.template.value,
    }


# ── GET /outreach/recipients/count ──────────────────────────────────

@router.get("/outreach/recipients/count")
async def recipient_count(
    recipient_filter: RecipientFilter = Query(...),
    db: Session = Depends(get_db),
):
    """Preview how many merchants match a filter before sending."""
    shops = _resolve_recipients(db, recipient_filter)
    return {"filter": recipient_filter.value, "count": len(shops)}


# ── GET /outreach/history ──────────────────────────────────────────

@router.get("/outreach/history")
async def outreach_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(OutreachLog).order_by(OutreachLog.sent_at.desc())
    total = q.count()
    logs = q.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "history": [
            {
                "id": l.id,
                "recipient_email": l.recipient_email,
                "recipient_shop": l.recipient_shop,
                "subject": l.subject,
                "body": l.body,
                "status": l.status,
                "sent_at": str(l.sent_at) if l.sent_at else None,
            }
            for l in logs
        ],
        "total": total,
        "page": page,
    }

"""
SuperAdmin outreach endpoints — SES email integration.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import OutreachLog, Shop
from src.ecommerce.services.email_service import send_email, send_bulk_email
from src.ecommerce.services.email_templates import TEMPLATE_REGISTRY
from .auth import verify_admin_token
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(verify_admin_token)])


# ── Request / response models ──────────────────────────────────────

class TemplateName(str, Enum):
    welcome = "welcome"
    upgrade = "upgrade"
    credit_limit = "credit_limit"
    enterprise = "enterprise"


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
            recipients.append({"email": shop.domain, "shop": shop.domain})

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
        else:
            raise HTTPException(status_code=400, detail="Unsupported template")
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f"Missing template params: {exc}")

    recipient_email = params.get("email", shop.domain)

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

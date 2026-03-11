"""
SuperAdmin outreach endpoints — dummy SES implementation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import OutreachLog, Shop
from .auth import verify_admin_token
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(verify_admin_token)])


class SendEmailRequest(BaseModel):
    to_emails: list[str] = []
    merchant_domains: list[str] = []
    subject: str
    body: str


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

    logs = []
    for r in recipients:
        log = OutreachLog(
            recipient_email=r["email"],
            recipient_shop=r["shop"],
            subject=req.subject,
            body=req.body,
            status="dummy",
        )
        db.add(log)
        logs.append(log)

    db.commit()

    logger.info(
        "[Outreach] dummy_send subject=%r recipients=%d", req.subject, len(recipients)
    )

    return {
        "message": f"Email queued for {len(recipients)} recipient(s) (dummy mode)",
        "recipients": len(recipients),
        "status": "dummy",
    }


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

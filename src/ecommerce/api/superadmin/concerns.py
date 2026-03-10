"""
SuperAdmin concerns endpoints — dummy implementation with Gmail prep.

Also provides the merchant-facing submit-concern endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import ConcernLog
from .auth import verify_admin_token

router = APIRouter()

# -- Admin-only endpoints (JWT protected) --

admin_router = APIRouter(dependencies=[Depends(verify_admin_token)])


@admin_router.get("/concerns")
async def list_concerns(db: Session = Depends(get_db)):
    concerns = (
        db.query(ConcernLog)
        .order_by(ConcernLog.created_at.desc())
        .limit(100)
        .all()
    )
    return {
        "concerns": [
            {
                "id": c.id,
                "shop_domain": c.shop_domain,
                "email": c.email,
                "subject": c.subject,
                "message": c.message,
                "status": c.status,
                "admin_reply": c.admin_reply,
                "created_at": str(c.created_at) if c.created_at else None,
            }
            for c in concerns
        ],
        "source": "database",
    }


class ReplyRequest(BaseModel):
    reply: str


@admin_router.post("/concerns/{concern_id}/reply")
async def reply_concern(
    concern_id: int,
    body: ReplyRequest,
    db: Session = Depends(get_db),
):
    concern = db.query(ConcernLog).filter(ConcernLog.id == concern_id).first()
    if not concern:
        raise HTTPException(status_code=404, detail="Concern not found")

    concern.admin_reply = body.reply
    concern.status = "replied"
    db.add(concern)
    db.commit()

    return {"message": "Reply saved", "concern_id": concern_id}


router.include_router(admin_router)


# -- Merchant-facing endpoint (no admin JWT required; protected by Shopify session at the proxy layer) --

class SubmitConcernRequest(BaseModel):
    shop_domain: str
    email: str = ""
    subject: str
    message: str


@router.post("/submit-concern")
async def submit_concern(body: SubmitConcernRequest, db: Session = Depends(get_db)):
    concern = ConcernLog(
        shop_domain=body.shop_domain,
        email=body.email,
        subject=body.subject,
        message=body.message,
        status="open",
    )
    db.add(concern)
    db.commit()
    db.refresh(concern)

    return {"message": "Concern submitted successfully", "concern_id": concern.id}

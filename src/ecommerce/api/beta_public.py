"""
Public Beta Signup endpoints — no authentication required.

These are accessible via tokenized invite links sent to prospective merchants.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import BetaEnrollment, Shop, User
from src.shared.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/beta")

_SHOPIFY_INSTALL_URL = "https://admin.shopify.com/oauth/install?client_id=315cfaf63c9baf27e4ba9a22b91b168e"
_BETA_DURATION_DAYS = 42


class BetaSignupRequest(BaseModel):
    store_name: str
    contact_email: str
    shop_domain: Optional[str] = None
    product_category: Optional[str] = None
    target_markets: Optional[str] = None
    purpose: Optional[str] = None


@router.get("/signup/{token}")
async def validate_beta_token(token: str, db: Session = Depends(get_db)):
    """Validate an invite token and return status info for the signup form."""
    enrollment = db.query(BetaEnrollment).filter(
        BetaEnrollment.invite_token == token
    ).first()

    if not enrollment:
        raise HTTPException(status_code=404, detail="招待リンクが無効、または期限切れです")

    if enrollment.status not in ("invited", "accepted"):
        raise HTTPException(
            status_code=410,
            detail="この招待リンクは既に使用されています"
        )

    return {
        "valid": True,
        "status": enrollment.status,
        "shop_domain": enrollment.shop_domain,
    }


@router.post("/signup/{token}")
async def submit_beta_signup(
    token: str, req: BetaSignupRequest, db: Session = Depends(get_db)
):
    """Submit the beta signup form. Marks enrollment as accepted and prepares for install."""
    enrollment = db.query(BetaEnrollment).filter(
        BetaEnrollment.invite_token == token
    ).first()

    if not enrollment:
        raise HTTPException(status_code=404, detail="招待リンクが無効、または期限切れです")

    if enrollment.status not in ("invited",):
        raise HTTPException(
            status_code=410,
            detail="この招待リンクは既に使用されています"
        )

    now = datetime.now(timezone.utc)

    enrollment.store_name = req.store_name
    enrollment.contact_email = req.contact_email
    enrollment.purpose = req.purpose
    enrollment.product_category = req.product_category
    enrollment.target_markets = req.target_markets
    enrollment.accepted_at = now

    # Update shop_domain if provided (merchant may specify their actual store URL)
    if req.shop_domain:
        domain = req.shop_domain.strip()
        if not domain.endswith(".myshopify.com"):
            domain = f"{domain}.myshopify.com"
        # Check if another enrollment already exists for this domain
        existing = db.query(BetaEnrollment).filter(
            BetaEnrollment.shop_domain == domain,
            BetaEnrollment.id != enrollment.id,
        ).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail="このストアは既にベータプログラムに登録されています"
            )
        enrollment.shop_domain = domain

    # Check if shop already exists (they installed before getting invited)
    shop = db.query(Shop).filter(Shop.domain == enrollment.shop_domain).first()
    if shop:
        shop.is_beta_tester = True
        shop.current_plan_name = "Pro"
        shop.last_plan_name = "Pro"
        beta_expires = now + timedelta(days=_BETA_DURATION_DAYS)
        shop.access_expires_at = beta_expires
        shop.pending_plan_name = "Free"
        shop.pending_plan_effective_at = beta_expires
        shop.last_plan_change_type = "beta_grant"
        shop.last_plan_change_at = now
        shop.monthly_rewrites_used = 0
        shop.monthly_missions_used = 0
        shop.monthly_image_generations_used = 0
        shop.free_trial_expires_at = None
        enrollment.status = "active"
        enrollment.activated_at = now

        # Update user email if we have one
        user = db.query(User).filter(User.username == enrollment.shop_domain).first()
        if user and not user.email and req.contact_email:
            user.email = req.contact_email

        logger.info("[BetaSignup] Existing shop %s activated on Pro", enrollment.shop_domain)
    else:
        enrollment.status = "accepted"
        logger.info("[BetaSignup] %s accepted, awaiting install", enrollment.shop_domain)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="このストアは既にベータプログラムに登録されています"
        )

    return {
        "success": True,
        "status": enrollment.status,
        "install_url": _SHOPIFY_INSTALL_URL,
        "message": "ベータ登録が完了しました！アプリをインストールしてProアクセスを有効にしてください。",
    }

"""
Shopify OAuth Routes

Handles OAuth installation, callback, token sync, and reinstall path logic.
"""

import secrets
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from src.shared.db.database import get_db
from src.ecommerce.db.models import Shop, User, Plan
from src.ecommerce.db.transactions import (
    get_shop_quota_context,
    store_shop_access_token,
    get_user_by_username,
)
from src.shared.security.security import (
    verify_shopify_redirect,
    SHOPIFY_API_KEY,
    SHOPIFY_API_SECRET,
)
from src.ecommerce.config.configs import SHOPIFY_UI_URL
from src.shared.logging.logger import get_logger

from .shared import SCOPES, SHOPIFY_REDIRECT_URI, TOKEN_SYNC_SECRET, _rid

logger = get_logger(__name__)
router = APIRouter()


async def _send_welcome_email_if_new(db: Session, shop_domain: str) -> None:
    """
    Send a welcome email if this is a brand-new user (no prior outreach).
    Best-effort: failures are logged but never block the install flow.
    """
    from src.ecommerce.db.models import OutreachLog

    existing = (
        db.query(OutreachLog)
        .filter(OutreachLog.recipient_shop == shop_domain, OutreachLog.subject.ilike("%welcome%"))
        .first()
    )
    if existing:
        logger.info("[WelcomeEmail] already sent for %s — skipping", shop_domain)
        return

    user = db.query(User).filter(User.username == shop_domain).first()
    recipient_email = user.email if user and user.email else None
    if not recipient_email:
        logger.info("[WelcomeEmail] skipped for %s — no email on file", shop_domain)
        return

    try:
        from src.ecommerce.services.email_templates import welcome_email
        from src.ecommerce.services.email_service import send_email

        subj, html_body, text_body = welcome_email(
            merchant_name=shop_domain,
            app_url=f"{SHOPIFY_UI_URL}/app",
        )
        await send_email(
            to=recipient_email,
            subject=subj,
            html_body=html_body,
            text_body=text_body,
        )
        log = OutreachLog(
            recipient_email=recipient_email,
            recipient_shop=shop_domain,
            subject=subj,
            body=text_body[:500],
            status="sent",
        )
        db.add(log)
        db.commit()
        logger.info("[WelcomeEmail] sent to %s for %s", recipient_email, shop_domain)
    except Exception as e:
        logger.warning("[WelcomeEmail] failed for %s: %s", shop_domain, e)


# =============================================================================
# OAuth Entry Point (Install App)
# =============================================================================

@router.get("/")
async def install_app(request: Request, shop: str = Query(..., description="Shopify Shop Domain")):
    """
    Redirects the user to Shopify's OAuth authorization page.
    """
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")
    
    logger.info("[Install] start rid=%s shop=%s", _rid(request), shop)

    state = secrets.token_hex(16)
    
    authorization_url = (
        f"https://{shop}/admin/oauth/authorize?"
        f"client_id={SHOPIFY_API_KEY}&"
        f"scope={SCOPES}&"
        f"redirect_uri={SHOPIFY_REDIRECT_URI}&"
        f"state={state}"
    )
    
    return RedirectResponse(url=authorization_url, status_code=307)


# =============================================================================
# OAuth Callback
# =============================================================================

@router.get("/api/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    params = dict(request.query_params)
    
    try:
        verify_shopify_redirect(params)
    except HTTPException as e:
        logger.error(f"OAuth redirect verification failed: {e.detail}")
        raise

    code = params.get("code")
    shop = params.get("shop")
    host = params.get("host")

    if not code or not shop:
        raise HTTPException(status_code=400, detail="Missing code or shop parameter")

    logger.info(f"[OAuth Callback] Starting token exchange for shop={shop}, host={host}")

    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code
    }

    import httpx
    try:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(token_url, json=payload)
        except PermissionError as e:
            logger.warning("SSL init failed for OAuth token exchange; using insecure client: %s", e)
            async with httpx.AsyncClient(verify=False) as client:
                response = await client.post(token_url, json=payload)

        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access_token")
        
        logger.info(f"Successfully exchanged token for shop: {shop}")
        logger.info(f"Auth callback params: host={host}, timestamp={params.get('timestamp')}")
        store_shop_access_token(db, shop, access_token)
        await _send_welcome_email_if_new(db, shop)

        # Redirect to the Remix UI's login route to ensure the UI also authenticates
        ui_login_url = f"{SHOPIFY_UI_URL}/auth/login?shop={shop}"
        if host:
            ui_login_url += f"&host={host}"
        logger.info(f"Redirecting to UI login for secondary handshake: {ui_login_url}")
        return RedirectResponse(url=ui_login_url)

    except httpx.HTTPStatusError as e:
        logger.error(f"Token exchange failed: {e.response.text}")
        raise HTTPException(status_code=400, detail="Failed to exchange access token")
    except Exception as e:
        logger.error(f"Unexpected error during token exchange: {e}")
        raise HTTPException(status_code=500, detail="Internal OAuth Error")


# =============================================================================
# Token Sync (From UI to API)
# =============================================================================

@router.post("/api/admin/sync-token")
async def sync_token(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Accepts a Shopify access token from the UI after its OAuth completes,
    and stores it in the API DB so proxy endpoints have credentials.
    Protected by a shared secret header.
    """
    if not TOKEN_SYNC_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfigured: TOKEN_SYNC_SECRET not set")

    provided_secret = request.headers.get("X-Token-Sync-Secret")
    if not provided_secret or not secrets.compare_digest(provided_secret, TOKEN_SYNC_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    shop = payload.get("shop")
    access_token = payload.get("access_token")
    token_type = payload.get("token_type", "offline")  # Default to offline if not specified
    force = bool(payload.get("force", False))

    if not shop or not access_token:
        raise HTTPException(status_code=400, detail="Missing shop or access_token")

    logger.info("[SyncToken] start rid=%s shop=%s type=%s force=%s", _rid(request), shop, token_type, force)
    store_shop_access_token(db, shop, access_token, token_type=token_type, force=force)
    await _send_welcome_email_if_new(db, shop)
    return Response(status_code=204)


# =============================================================================
# Reinstall Path Finder
# =============================================================================

@router.get("/api/admin/reinstall-path")
async def reinstall_pathfinder(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Internal helper for the UI to decide where a (re)install should land.

    Paths:
    - Paid + grace active (access_expires_at in future): /app (Home) and keep prior plan active
    - Paid + expired: /app/pricing?returning_paid=1
    - Free: /app/dashboard if credits>0 else /app/pricing
    """
    shop_domain = (request.query_params.get("shop") or "").strip()
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    ctx = get_shop_quota_context(db, shop_domain)
    if not ctx:
        # Unknown shop: treat as Free new install
        return {"redirect_to": "/app/dashboard", "reason": "new_shop"}

    shop: Shop = ctx["shop"]
    last_plan = str(ctx.get("last_plan_name") or "").strip() or "Free"
    grace_active = bool(ctx.get("grace_active"))
    expired_paid = bool(ctx.get("expired_paid"))
    access_expires_at = ctx.get("access_expires_at")

    def _is_paid(name: str) -> bool:
        return str(name or "").strip().lower() in ("basic", "standard", "pro")

    # Always mark the DB row active on reinstall/login. Token is handled by the UI token sync.
    try:
        shop.is_active = True
        db.add(shop)
        db.commit()
        db.refresh(shop)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    if _is_paid(last_plan):
        if bool(ctx.get("grace_mode")):
            # Grace: keep their paid tier for gating
            try:
                shop.current_plan_name = last_plan
                db.add(shop)
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
            return {
                "redirect_to": "/app",
                "reason": "paid_grace_active",
                "access_expires_at": access_expires_at.isoformat() if access_expires_at else None,
            }

        # Expired paid: force them back to pricing and prevent fallback to Free.
        try:
            shop.current_plan_name = None
            db.add(shop)
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {
            "redirect_to": "/app/pricing?returning_paid=1",
            "reason": "paid_expired",
            "access_expires_at": access_expires_at.isoformat() if access_expires_at else None,
        }

    # Free path: preserve lifetime credits
    remaining = int(getattr(shop, "lifetime_rewrites_remaining", 0) or 0)
    if remaining > 0:
        # Ensure plan names are initialized for legacy rows
        try:
            if not (getattr(shop, "last_plan_name", None) or "").strip():
                shop.last_plan_name = "Free"
            if not (getattr(shop, "current_plan_name", None) or "").strip():
                shop.current_plan_name = "Free"
            db.add(shop)
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {"redirect_to": "/app/dashboard", "reason": "free_with_credits"}
    return {"redirect_to": "/app/pricing", "reason": "free_no_credits"}

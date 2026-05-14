"""
Shopify Webhook Routes

Handles all Shopify webhooks including subscription, compliance, install/uninstall.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session

from src.ecommerce.api.models import OnboardingRequest
from src.shared.db.database import get_db
from src.ecommerce.db.models import Shop, User, Plan, UsageRecord
from src.ecommerce.db.transactions import get_plan_by_name, get_user_by_username
from src.shared.security.security import verify_webhook_signature
from src.ecommerce.services.onboarding_service import onboard_user
from src.shared.logging.logger import get_logger, get_security_logger

from .shared import _rid

logger = get_logger(__name__)
security_logger = get_security_logger("security.webhooks")
router = APIRouter()


# =============================================================================
# Subscription Webhook
# =============================================================================

@router.post("/webhooks/subscription-activated")
async def handle_subscription_activated(
    request: Request,
    db: Session = Depends(get_db)
):
    await verify_webhook_signature(request)
    logger.info(
        "[Webhook] subscription_activated rid=%s shop=%s webhook_id=%s",
        _rid(request),
        (request.headers.get("X-Shopify-Shop-Domain") or "").strip() or "-",
        (request.headers.get("X-Shopify-Webhook-Id") or "").strip() or "-",
    )
    
    try:
        payload = await request.json()
        # Shopify standard webhook for APP_SUBSCRIPTIONS_UPDATE
        # Check for both custom payload and standard Shopify payload
        app_subscription = payload.get('app_subscription', {})
        status = "ACTIVE"
        
        if app_subscription:
            # Standard Shopify webhook
            shop_domain = request.headers.get("X-Shopify-Shop-Domain")
            plan_name = app_subscription.get('name')
            status = str(app_subscription.get('status') or "").strip() or "ACTIVE"
        else:
            # Fallback for manual/custom triggers
            shop_domain = payload.get('myshopify_domain')
            plan_name = payload.get('billing_plan') 
            status = "ACTIVE"
        
        if not shop_domain or not plan_name:
            logger.warning("Webhook payload missing shop domain or plan name")
            return Response(status_code=200)

        # Shopify subscription names can differ from our internal plan names (e.g. promo/annual SKUs).
        # Canonicalize to our DB plan names so quota + gating stays stable.
        raw_plan_name = str(plan_name or "").strip()
        pn = raw_plan_name.lower()
        try:
            import re

            def has_word(w: str) -> bool:
                return re.search(rf"\b{re.escape(w)}\b", pn) is not None
        except Exception:
            # Extremely defensive fallback; prefer not to match "promo" as "pro"
            def has_word(w: str) -> bool:  # type: ignore[no-redef]
                return f" {w} " in f" {pn} "

        if has_word("basic"):
            plan_name = "Basic"
        elif has_word("standard"):
            plan_name = "Standard"
        elif has_word("pro"):
            plan_name = "Pro"
        elif has_word("free"):
            plan_name = "Free"
        else:
            plan_name = raw_plan_name

        plan = get_plan_by_name(db, plan_name)
        if not plan:
            logger.warning(f"Webhook received for unknown plan: raw={raw_plan_name} canonical={plan_name}")
            return Response(status_code=200)

        def _tier_rank(name: str | None) -> int:
            n = str(name or "").strip().lower()
            if n == "pro":
                return 3
            if n == "standard":
                return 2
            if n == "basic":
                return 1
            return 0

        # Persist paid-cycle expiry + last/current plan on the Shop row.
        # This enables a "grace period" after uninstall, even if Shopify cancels the subscription immediately.
        try:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
            downgrade_scheduled = False
            if shop_rec:
                shop_rec.is_active = True
                shop_rec.last_shopify_subscription_status = str(status or "").strip() or None

                current_name = (getattr(shop_rec, "current_plan_name", None) or "").strip() or str(getattr(plan, "name", "") or "").strip()
                current_rank = _tier_rank(current_name)
                new_rank = _tier_rank(plan.name)

                # Non-active status means Shopify indicates cancellation/expiry. We schedule a downgrade to Free
                # at the end of the already-paid window (access_expires_at).
                if app_subscription and str(status or "").strip().upper() != "ACTIVE":
                    shop_rec.last_plan_change_type = "cancel"
                    shop_rec.last_plan_change_at = now
                    shop_rec.pending_plan_name = "Free"
                    # Honor existing prepaid window; if missing, be conservative and downgrade soon.
                    eff = getattr(shop_rec, "access_expires_at", None) or (now + timedelta(days=1))
                    shop_rec.pending_plan_effective_at = eff
                else:
                    # ACTIVE update: can be upgrade or downgrade.
                    if new_rank < current_rank:
                        # Downgrade: schedule at end of current paid cycle (do not change current_plan_name yet).
                        shop_rec.last_plan_change_type = "downgrade"
                        shop_rec.last_plan_change_at = now
                        shop_rec.pending_plan_name = plan.name
                        eff = getattr(shop_rec, "access_expires_at", None) or (now + timedelta(days=30))
                        shop_rec.pending_plan_effective_at = eff
                        downgrade_scheduled = True
                    else:
                        # Upgrade or same tier: apply immediately.
                        shop_rec.last_plan_change_type = "upgrade" if new_rank > current_rank else "none"
                        shop_rec.last_plan_change_at = now
                        shop_rec.current_plan_name = plan.name
                        shop_rec.last_plan_name = plan.name
                        shop_rec.pending_plan_name = None
                        shop_rec.pending_plan_effective_at = None
                        # Manual plan change/activation means it's NOT a reinstall grace display state.
                        shop_rec.last_uninstalled_at = None
                        # For paid plans, set a hard expiry window (30 days from activation)
                        # and clear the free trial (they've upgraded).
                        # For Free, clear any paid expiry.
                        if str(plan.name or "").strip().lower() in ("basic", "standard", "pro"):
                            shop_rec.access_expires_at = now + timedelta(days=30)
                            shop_rec.free_trial_expires_at = None
                        else:
                            shop_rec.access_expires_at = None
                db.add(shop_rec)
                db.commit()
        except Exception as e:
            logger.warning(f"[Webhook] unable to persist shop plan/expiry for {shop_domain}: {e}")
            try:
                db.rollback()
            except Exception:
                pass

        # ACTION: Explicitly update the User's plan in DB to ensure immediate effect
        # Wrap in try/except to avoid failing when test DB tables are absent.
        try:
            user = get_user_by_username(db, shop_domain)
            if user:
                # On downgrade/cancel we do NOT change user.plan_id until the downgrade is effective.
                if str(status or "").strip().upper() == "ACTIVE" and not downgrade_scheduled:
                    logger.info(f"Updating plan for {shop_domain} to {plan.name} (ID: {plan.id})")
                    user.plan_id = plan.id
                    db.commit()
                    db.refresh(user)

            # Also reset product rewrite usage when a plan changes (new billing cycle anchor)
            try:
                shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
                if shop_rec:
                    from datetime import datetime, timedelta, timezone
                    now = datetime.now(timezone.utc)
                    shop_rec.monthly_rewrites_used = 0
                    shop_rec.monthly_cost_accumulated = 0
                    shop_rec.fair_use_last_notified_at = None
                    shop_rec.reset_anchor_date = now
                    shop_rec.next_reset_date = now + timedelta(days=30)
                    db.add(shop_rec)
                    db.commit()
            except Exception as e:
                logger.warning(f"Shop rewrite reset skipped for {shop_domain}: {e}")
        except Exception as e:
            logger.warning(f"Plan update skipped for {shop_domain}: {e}")

        onboarding_req = OnboardingRequest(
            username=shop_domain,
            plan_id=plan.id,
            email=payload.get('email') or f"contact@{shop_domain}"
        )
        
        try:
            onboard_user(db, onboarding_req)
            logger.info(f"Webhook successfully onboarded user: {shop_domain}")
        except HTTPException as e:
            if e.status_code == 409:
                logger.info(f"User {shop_domain} already exists. Skipping creation.")
            else:
                logger.error(f"Onboarding error processing webhook: {e.detail}")
        except Exception as e:
            logger.error(f"Unexpected error processing webhook: {e}")

    except Exception as e:
        logger.error(f"Error parsing webhook payload: {e}")
        return Response(status_code=200)

    return Response(status_code=200)


# =============================================================================
# Compliance (GDPR) Webhooks
# =============================================================================

@router.post("/api/webhooks/compliance")
async def compliance_webhooks(request: Request, db: Session = Depends(get_db)):
    """
    Mandatory Shopify GDPR webhooks endpoint.

    Requirements:
    - Extract X-Shopify-Topic immediately
    - Verify webhook HMAC using RAW request body bytes
    - Return 200 OK quickly (avoid retries)
    - Log to security.log for audit
    """
    # Requirement 1: topic first (no JSON parsing yet)
    topic = (request.headers.get("X-Shopify-Topic") or "").strip().lower()
    shop_domain = (request.headers.get("X-Shopify-Shop-Domain") or "").strip()
    webhook_id = (request.headers.get("X-Shopify-Webhook-Id") or "").strip()

    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")

    # Requirement 4: reject immediately if verification fails
    try:
        from src.shared.security.security import verify_shopify_webhook, SHOPIFY_API_SECRET
        verify_shopify_webhook(raw_body=raw_body, hmac_header=hmac_header, api_secret=SHOPIFY_API_SECRET)
    except HTTPException:
        # Keep audit trail even for rejected requests (do not log raw body)
        security_logger.warning(
            f"[GDPR] REJECTED topic={topic or '<missing>'} shop={shop_domain or '<missing>'} "
            f"webhook_id={webhook_id or '<missing>'} body_len={len(raw_body)}"
        )
        raise

    # Audit log (success path) — avoid storing PII; do not log payload contents
    security_logger.info(
        f"[GDPR] ACCEPTED topic={topic or '<missing>'} shop={shop_domain or '<missing>'} "
        f"webhook_id={webhook_id or '<missing>'} body_len={len(raw_body)}"
    )

    # Requirement 2: keep handlers lightweight and always return 200 fast.
    # We do best-effort DB cleanup for shop/redact; other topics are acknowledgements.
    try:
        if topic == "customers/data_request":
            security_logger.info(
                f"[GDPR] customers/data_request acknowledged shop={shop_domain or '<missing>'} "
                f"(no customer PII stored by Aganim AI)"
            )
            return {"status": "ok", "message": "No customer personal data stored."}

        if topic == "customers/redact":
            security_logger.info(
                f"[GDPR] customers/redact acknowledged shop={shop_domain or '<missing>'} "
                f"(no customer-linked records to delete)"
            )
            return {"status": "ok", "message": "Customer data redaction acknowledged."}

        if topic == "shop/redact":
            # 48 hours after uninstall: delete all merchant-related records (best-effort).
            # NOTE: We do not log request payload; shop_domain is from header.
            if shop_domain:
                user = db.query(User).filter(User.username == shop_domain).first()
                if user:
                    # Delete usage records for this merchant
                    db.query(UsageRecord).filter(UsageRecord.user_id == user.id).delete(synchronize_session=False)
                    db.delete(user)

                shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
                if shop_rec:
                    db.delete(shop_rec)

                db.commit()
                security_logger.info(f"[GDPR] shop/redact deleted merchant records shop={shop_domain}")
            else:
                security_logger.warning("[GDPR] shop/redact missing X-Shopify-Shop-Domain header")

            return {"status": "ok", "message": "Shop data redaction processed."}

        # Unknown/other: acknowledge to avoid retries
        security_logger.info(f"[GDPR] unknown_topic acknowledged topic={topic or '<missing>'} shop={shop_domain or '<missing>'}")
        return {"status": "ok", "message": "Webhook acknowledged."}
    except Exception as e:
        # Never block Shopify retries with long work; log and ACK.
        try:
            db.rollback()
        except Exception:
            pass
        security_logger.error(
            f"[GDPR] handler_error topic={topic or '<missing>'} shop={shop_domain or '<missing>'} err={e}"
        )
        return {"status": "ok", "message": "Webhook acknowledged."}


# =============================================================================
# App Uninstall Webhook
# =============================================================================

@router.post("/webhooks/app/uninstalled")
async def handle_app_uninstalled(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle app/uninstalled webhook.
    Keep this handler very fast to avoid Shopify timeouts.
    """
    await verify_webhook_signature(request)
    try:
        payload = await request.json()
        shop_domain = payload.get("myshopify_domain") or request.headers.get("X-Shopify-Shop-Domain")

        logger.info("[Webhook] app_uninstalled rid=%s shop=%s", _rid(request), shop_domain or "-")

        if shop_domain:
            # IMPORTANT: do not delete Shop rows on uninstall.
            # We need to preserve lifetime credits for Free plan reinstalls.
            try:
                shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
                if shop_rec:
                    # Persist last_plan_name so we can route reinstalls correctly.
                    # Prefer the Shop row's current_plan_name; fall back to the User's plan if available.
                    try:
                        current = (getattr(shop_rec, "current_plan_name", None) or "").strip()
                        if not current:
                            user = get_user_by_username(db, shop_domain)
                            if user and getattr(user, "plan", None):
                                current = (getattr(user.plan, "name", None) or "").strip()
                        if current:
                            shop_rec.last_plan_name = current
                    except Exception:
                        pass

                    shop_rec.is_active = False
                    try:
                        from datetime import datetime, timezone
                        shop_rec.last_uninstalled_at = datetime.now(timezone.utc)
                    except Exception:
                        pass
                    # Token is invalid after uninstall; keep row but clear token.
                    shop_rec.access_token = ""
                    db.add(shop_rec)
                    db.commit()
            except Exception as e:
                logger.warning(f"Unable to deactivate shop record for {shop_domain}: {e}")
                db.rollback()

    except Exception as e:
        logger.error(f"Error handling app/uninstalled webhook: {e}")

    # Always return 200 quickly to avoid retries/timeouts
    return Response(status_code=200)


# =============================================================================
# App Install Webhook
# =============================================================================

@router.post("/webhooks/app/install")
async def handle_app_install(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    App install (or reinstall) webhook.

    Requirements:
    - If Shop exists: set is_active=True and keep lifetime_rewrites_remaining (do NOT reset).
    - Else: create Shop with lifetime_rewrites_remaining=10.
    """
    await verify_webhook_signature(request)
    shop_domain = (request.headers.get("X-Shopify-Shop-Domain") or "").strip()
    try:
        payload = await request.json()
        shop_domain = (payload.get("myshopify_domain") or shop_domain or "").strip()
    except Exception:
        payload = {}

    if not shop_domain:
        return Response(status_code=200)

    logger.info("[Webhook] app_install rid=%s shop=%s", _rid(request), shop_domain)

    try:
        shop_rec = db.query(Shop).filter(Shop.domain == shop_domain).first()
        if shop_rec:
            previously_inactive = not bool(getattr(shop_rec, "is_active", True))
            shop_rec.is_active = True
            # Preserve existing lifetime credits (critical).
            # Also preserve monthly counters; monthly reset is handled elsewhere.
            if previously_inactive:
                shop_rec.welcome_back_pending = True
            db.add(shop_rec)
            db.commit()
            db.refresh(shop_rec)
        else:
            # New shop: create a row with 10 lifetime credits + 7-day trial window.
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            shop_rec = Shop(
                domain=shop_domain,
                access_token="",
                monthly_rewrites_used=0,
                lifetime_rewrites_remaining=10,
                is_active=True,
                welcome_back_pending=False,
                free_trial_expires_at=now + timedelta(days=7),
            )
            db.add(shop_rec)
            db.commit()
            db.refresh(shop_rec)

        # Ensure a User row exists (billing/quota identity). Default to Free plan.
        user = get_user_by_username(db, shop_domain)
        if not user:
            free_plan = db.query(Plan).filter(Plan.name == "Free").first()
            if free_plan:
                user = User(username=shop_domain, email=None, plan_id=free_plan.id)
                db.add(user)
                db.commit()

        # Auto-upgrade beta merchants: if there's an accepted enrollment, activate Pro
        try:
            from src.ecommerce.db.models import BetaEnrollment
            beta_enrollment = db.query(BetaEnrollment).filter(
                BetaEnrollment.shop_domain == shop_domain,
                BetaEnrollment.status == "accepted",
            ).first()
            if beta_enrollment:
                from datetime import datetime, timedelta, timezone as tz
                now_utc = datetime.now(tz.utc)
                shop_rec.is_beta_tester = True
                shop_rec.current_plan_name = "Pro"
                shop_rec.last_plan_name = "Pro"
                beta_expires = now_utc + timedelta(days=42)
                shop_rec.access_expires_at = beta_expires
                shop_rec.pending_plan_name = "Free"
                shop_rec.pending_plan_effective_at = beta_expires
                shop_rec.last_plan_change_type = "beta_grant"
                shop_rec.last_plan_change_at = now_utc
                shop_rec.monthly_rewrites_used = 0
                shop_rec.monthly_missions_used = 0
                shop_rec.monthly_image_generations_used = 0
                shop_rec.free_trial_expires_at = None
                beta_enrollment.status = "active"
                beta_enrollment.activated_at = now_utc
                # Set user email from enrollment if available
                if beta_enrollment.contact_email and user and not user.email:
                    user.email = beta_enrollment.contact_email
                db.add(shop_rec)
                db.commit()
                logger.info("[Webhook] Beta auto-upgrade: %s activated on Pro (expires %s)", shop_domain, beta_expires.isoformat())
        except Exception as beta_err:
            logger.warning("[Webhook] Beta auto-upgrade check failed for %s: %s", shop_domain, beta_err)
            try:
                db.rollback()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[Webhook] app_install failed shop={shop_domain}: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    return Response(status_code=200)

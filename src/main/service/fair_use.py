import os
from datetime import datetime, timedelta, timezone, date
import httpx
from sqlalchemy.orm import Session

from src.main.db.db_models import Shop, UsageRecord, User
from src.main.db.db_transactions import sync_usage_limits
from src.main.logging.logger import get_logger

logger = get_logger(__name__)


# $10 per 1,000,000 output tokens (per user request)
USD_PER_OUTPUT_TOKEN = 10.0 / 1_000_000.0
FAIR_USE_USD_THRESHOLD = 150.0
DEGRADE_USD_THRESHOLD = 150.0 * 10  # 10x


def _cycle_start_date_from_shop(shop: Shop) -> date:
    """
    We align internal token metering to the same 30-day shop cycle used for rewrites.
    If next_reset_date is present, the current cycle start is (next_reset_date - 30 days).
    """
    if isinstance(shop.next_reset_date, datetime):
        nr = shop.next_reset_date
        if nr.tzinfo is None:
            nr = nr.replace(tzinfo=timezone.utc)
        return (nr - timedelta(days=30)).date()
    # Fallback: use today's date as a stable key (will self-heal once next_reset_date exists)
    return datetime.now(timezone.utc).date()


def record_token_usage(db: Session, shop_domain: str, output_tokens: int) -> int:
    """
    Internal-only token accounting used for margin monitoring.
    Stores tokens in UsageRecord.usage_count (db column: token_count).

    NOTE: We treat this as *output tokens* for cost estimation. If you only have total_tokens,
    pass total_tokens here as a conservative approximation.
    """
    if not shop_domain:
        return 0
    if not output_tokens or int(output_tokens) <= 0:
        return 0

    # Ensure shop reset fields are current so our cycle start stays consistent
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if shop:
        shop = sync_usage_limits(db, shop)
    else:
        return 0

    user = db.query(User).filter(User.username == shop_domain).first()
    if not user:
        return 0

    cycle_start = _cycle_start_date_from_shop(shop)
    rec = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user.id, UsageRecord.billing_cycle_start == cycle_start)
        .first()
    )
    if not rec:
        rec = UsageRecord(user_id=user.id, billing_cycle_start=cycle_start, usage_count=0)
        db.add(rec)

    rec.usage_count = int(rec.usage_count or 0) + int(output_tokens)
    db.commit()
    db.refresh(rec)
    return int(rec.usage_count or 0)


def _get_cycle_token_total(db: Session, shop_domain: str) -> int:
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        return 0
    shop = sync_usage_limits(db, shop)

    user = db.query(User).filter(User.username == shop_domain).first()
    if not user:
        return 0

    cycle_start = _cycle_start_date_from_shop(shop)
    rec = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user.id, UsageRecord.billing_cycle_start == cycle_start)
        .first()
    )
    return int(rec.usage_count or 0) if rec else 0


def _usd_cost_from_tokens(output_tokens: int) -> float:
    return float(output_tokens) * USD_PER_OUTPUT_TOKEN


def is_fair_use_violated(db: Session, shop_domain: str) -> bool:
    """
    Internal flagging only:
    - Basic/Standard => always False (already capped by rewrite count)
    - Pro => True if estimated monthly token cost exceeds $150
    """
    user = db.query(User).filter(User.username == shop_domain).first()
    if not user or not user.plan:
        return False

    if user.plan.name in ("Basic", "Standard"):
        return False
    if user.plan.name != "Pro":
        return False

    total = _get_cycle_token_total(db, shop_domain)
    return _usd_cost_from_tokens(total) > FAIR_USE_USD_THRESHOLD


def should_degrade_model(db: Session, shop_domain: str) -> bool:
    """
    Optional graceful degradation:
    If Pro shop exceeds 10x threshold, we can downgrade the model to reduce costs.
    """
    user = db.query(User).filter(User.username == shop_domain).first()
    if not user or not user.plan or user.plan.name != "Pro":
        return False

    total = _get_cycle_token_total(db, shop_domain)
    return _usd_cost_from_tokens(total) > DEGRADE_USD_THRESHOLD


def notify_fair_use_if_needed(db: Session, shop_domain: str):
    """
    If the Pro shop crossed the fair-use threshold, send an internal notification.
    This never blocks the merchant.
    """
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        return
    shop = sync_usage_limits(db, shop)

    user = db.query(User).filter(User.username == shop_domain).first()
    if not user or not user.plan or user.plan.name != "Pro":
        return

    total = _get_cycle_token_total(db, shop_domain)
    cost = _usd_cost_from_tokens(total)
    if cost <= FAIR_USE_USD_THRESHOLD:
        return

    # Notify once per cycle (avoid spamming logs/webhooks)
    now = datetime.now(timezone.utc)
    cycle_start_dt = datetime.combine(_cycle_start_date_from_shop(shop), datetime.min.time(), tzinfo=timezone.utc)
    last = shop.fair_use_last_notified_at
    if isinstance(last, datetime) and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if isinstance(last, datetime) and last >= cycle_start_dt:
        return

    msg = f"Shop {shop_domain} has reached Fair Use Threshold ($150 cost). Total tokens: {total}."
    logger.warning(f"[FairUse] {msg} est_cost_usd={cost:.2f}")

    # Optional webhook
    url = (os.getenv("FAIR_USE_WEBHOOK_URL") or "").strip()
    if url:
        try:
            httpx.post(
                url,
                json={
                    "text": msg,
                    "shop": shop_domain,
                    "total_tokens": total,
                    "estimated_cost_usd": round(cost, 2),
                },
                timeout=3.0,
            )
        except Exception as e:
            logger.warning(f"[FairUse] Webhook notify failed: {e}")

    shop.fair_use_last_notified_at = now
    db.add(shop)
    db.commit()

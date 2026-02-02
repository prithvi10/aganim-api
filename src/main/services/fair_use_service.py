"""
FairUseService - Usage tracking and cost management.

Moved from service/fair_use.py to consolidate services.
"""

import os
from datetime import datetime, timedelta, timezone, date
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from src.main.config.configs import (
    FAIR_USE_COST_CAP,
    FAIR_USE_USD_PER_1M_INPUT,
    FAIR_USE_USD_PER_1M_OUTPUT,
    FAIR_USE_USD_PER_1M_REASONING,
    OPENAI_MODEL,
    OPENAI_MODEL_PRO,
    OPENAI_MODEL_DEGRADED,
)
from src.main.db.db_models import Shop, UsageRecord, User
from src.main.db.db_transactions import sync_usage_limits
from src.main.logging.logger import get_logger

logger = get_logger(__name__)


_USD_PER_INPUT_TOKEN = FAIR_USE_USD_PER_1M_INPUT / 1_000_000.0
_USD_PER_OUTPUT_TOKEN = FAIR_USE_USD_PER_1M_OUTPUT / 1_000_000.0
_USD_PER_REASONING_TOKEN = FAIR_USE_USD_PER_1M_REASONING / 1_000_000.0


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

def _extract_token_breakdown(usage: object) -> tuple[int, int, int, int]:
    """
    Best-effort extraction across OpenAI SDK variants.
    Returns: (prompt_tokens, completion_tokens, reasoning_tokens, total_tokens)
    """
    if usage is None:
        return (0, 0, 0, 0)

    # dict-like
    if isinstance(usage, dict):
        pt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        ct = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        rt = int(usage.get("reasoning_tokens") or 0)
        tt = int(usage.get("total_tokens") or (pt + ct + rt) or 0)
        if tt and not (pt or ct or rt):
            ct = tt
        return (pt, ct, rt, tt)

    pt = int(getattr(usage, "prompt_tokens", 0) or 0)
    ct = int(getattr(usage, "completion_tokens", 0) or 0)
    rt = int(getattr(usage, "reasoning_tokens", 0) or 0)
    tt = int(getattr(usage, "total_tokens", 0) or 0)

    if tt and not (pt or ct or rt):
        ct = tt
    if not tt:
        tt = pt + ct + rt
    return (pt, ct, rt, tt)


def _cost_usd(prompt_tokens: int, completion_tokens: int, reasoning_tokens: int) -> float:
    return (
        float(prompt_tokens) * _USD_PER_INPUT_TOKEN
        + float(completion_tokens) * _USD_PER_OUTPUT_TOKEN
        + float(reasoning_tokens) * _USD_PER_REASONING_TOKEN
    )


def get_base_model_for_shop(db: Session, shop_domain: str) -> str:
    """
    Pro shops default to OPENAI_MODEL_PRO; others default to OPENAI_MODEL.
    """
    try:
        user = db.query(User).filter(User.username == shop_domain).first()
        if user and user.plan and user.plan.name == "Pro":
            return OPENAI_MODEL_PRO
        return OPENAI_MODEL
    except SQLAlchemyError:
        # Fail-safe: if DB is not initialized (e.g., some CI test orders), default to cheap model.
        return OPENAI_MODEL


def should_throttle_for_cycle(db: Session, shop_domain: str) -> bool:
    """
    Throttle trigger (internal-only): if Pro shop's monthly_cost_accumulated > FAIR_USE_COST_CAP.
    """
    try:
        user = db.query(User).filter(User.username == shop_domain).first()
        if not user or not user.plan or user.plan.name != "Pro":
            return False
        shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        if not shop:
            return False
        shop = sync_usage_limits(db, shop)
        return float(shop.monthly_cost_accumulated or 0) > float(FAIR_USE_COST_CAP)
    except SQLAlchemyError:
        return False


def get_effective_model(db: Session, shop_domain: str, requested_model: str) -> str:
    """
    If fair-use throttle is active for this Pro shop, force the degraded model for the rest of the cycle.
    """
    if should_throttle_for_cycle(db, shop_domain):
        return OPENAI_MODEL_DEGRADED
    return requested_model


def record_cost_from_usage(
    db: Session,
    shop_domain: str,
    usage: object,
    *,
    model_used: str,
) -> float:
    """
    After an AI call, compute token cost and add it to Shop.monthly_cost_accumulated.
    Returns the updated monthly_cost_accumulated.
    """
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        return 0.0
    shop = sync_usage_limits(db, shop)

    pt, ct, rt, tt = _extract_token_breakdown(usage)

    # Internal accounting uses UsageRecord as well (best-effort). We treat completion tokens
    # as the "output tokens" for the $/1M math; if missing, fall back to total.
    to_record = int(ct or tt or 0)
    if to_record > 0:
        try:
            record_token_usage(db, shop_domain, to_record)
        except Exception:
            pass

    delta = _cost_usd(pt, ct or tt, rt)
    shop.monthly_cost_accumulated = float(shop.monthly_cost_accumulated or 0) + float(delta)
    db.add(shop)
    db.commit()
    db.refresh(shop)

    # Trigger: log once per cycle and allow future calls to be downgraded
    if shop.monthly_cost_accumulated > float(FAIR_USE_COST_CAP):
        _log_yellow_alert_if_needed(db, shop_domain, shop, tt, model_used)

    return float(shop.monthly_cost_accumulated or 0)


def _log_yellow_alert_if_needed(db: Session, shop_domain: str, shop: Shop, total_tokens: int, model_used: str):
    # Log once per cycle (avoid spamming)
    now = datetime.now(timezone.utc)
    cycle_start_dt = datetime.combine(_cycle_start_date_from_shop(shop), datetime.min.time(), tzinfo=timezone.utc)
    last = shop.fair_use_last_notified_at
    if isinstance(last, datetime) and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if isinstance(last, datetime) and last >= cycle_start_dt:
        return

    msg = (
        f"YELLOW_ALERT: Shop {shop_domain} exceeded Fair Use cap (${FAIR_USE_COST_CAP:.2f}). "
        f"monthly_cost_accumulated=${float(shop.monthly_cost_accumulated or 0):.2f} "
        f"last_call_total_tokens={int(total_tokens or 0)} model_used={model_used}"
    )
    logger.warning(msg)

    url = (os.getenv("FAIR_USE_WEBHOOK_URL") or "").strip()
    if url:
        try:
            httpx.post(
                url,
                json={
                    "text": msg,
                    "shop": shop_domain,
                    "monthly_cost_accumulated": float(shop.monthly_cost_accumulated or 0),
                    "cap": float(FAIR_USE_COST_CAP),
                    "last_call_total_tokens": int(total_tokens or 0),
                    "model_used": model_used,
                },
                timeout=3.0,
            )
        except Exception as e:
            logger.warning(f"[FairUse] Webhook notify failed: {e}")

    shop.fair_use_last_notified_at = now
    db.add(shop)
    db.commit()

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
    return float(output_tokens) * _USD_PER_OUTPUT_TOKEN


def is_fair_use_violated(db: Session, shop_domain: str) -> bool:
    """
    Internal flagging only:
    - Basic/Standard => always False (already capped by rewrite count)
    - Pro => True if monthly_cost_accumulated exceeds FAIR_USE_COST_CAP
    """
    user = db.query(User).filter(User.username == shop_domain).first()
    if not user or not user.plan:
        return False

    if user.plan.name in ("Basic", "Standard"):
        return False
    if user.plan.name != "Pro":
        return False

    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        return False
    shop = sync_usage_limits(db, shop)
    return float(shop.monthly_cost_accumulated or 0) > float(FAIR_USE_COST_CAP)


def should_degrade_model(db: Session, shop_domain: str) -> bool:
    """
    Backwards-compatible helper: throttle immediately when cap is exceeded (per policy),
    so requests switch to a standard-tier model for the rest of the billing cycle.
    """
    return should_throttle_for_cycle(db, shop_domain)


def notify_fair_use_if_needed(db: Session, shop_domain: str):
    """
    Backwards-compatible entrypoint.
    We now notify from record_cost_from_usage() after computing monthly_cost_accumulated.
    """
    return

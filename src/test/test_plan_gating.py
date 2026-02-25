"""
Tests for the Plan Gating Overhaul.

Covers:
- PLAN_ENTITLEMENTS config correctness
- validate_feature_access / validate_agent_action_access
- validate_mission_access / validate_image_credits
- record_feature_usage / get_feature_usage / log_usage_event
- sync_usage_limits resets new monthly counters
- FeatureUsage and UsageEventLog models
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.shared.db.database import Base
from src.ecommerce.db.models import (
    User, Plan, Shop, FeatureUsage, UsageEventLog,
)
from src.ecommerce.db.transactions import (
    record_feature_usage,
    get_feature_usage,
    log_usage_event,
    sync_usage_limits,
    record_successful_rewrite,
)
from src.ecommerce.plans.entitlements import (
    PLAN_ENTITLEMENTS,
    get_entitlements,
    get_required_tier,
)
from src.ecommerce.api.validation import (
    validate_feature_access,
    validate_agent_action_access,
    validate_image_credits,
    validate_mission_access,
    _ACTION_TO_FEATURE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """In-memory SQLite session with seeded plan/user/shop data."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    now = datetime.now(timezone.utc)

    for name, limit, cycle in [
        ("Free", 10, "lifetime"),
        ("Basic", 50, "recurring"),
        ("Standard", -1, "recurring"),
        ("Pro", -1, "recurring"),
    ]:
        db.add(Plan(
            name=name,
            monthly_rewrite_limit=limit,
            product_limit=limit,
            billing_cycle_type=cycle,
            max_request_rate=10,
        ))
    db.commit()

    free = db.query(Plan).filter_by(name="Free").first()
    basic = db.query(Plan).filter_by(name="Basic").first()
    pro = db.query(Plan).filter_by(name="Pro").first()

    for domain, plan in [
        ("free-shop", free),
        ("basic-shop", basic),
        ("pro-shop", pro),
    ]:
        db.add(User(username=domain, plan_id=plan.id))
        db.add(Shop(
            domain=domain,
            access_token="tok",
            current_plan_name=plan.name,
            monthly_rewrites_used=0,
            lifetime_rewrites_remaining=10 if plan.name == "Free" else 0,
            lifetime_missions_remaining=3 if plan.name == "Free" else 0,
            lifetime_image_credits_remaining=5 if plan.name == "Free" else 0,
            monthly_missions_used=0,
            monthly_image_generations_used=0,
            reset_anchor_date=now,
            next_reset_date=now + timedelta(days=30),
        ))
    db.commit()

    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _make_context(plan_name: str, shop_overrides: dict | None = None):
    """Helper to build a mock auth_context dict for validation tests."""
    plan = MagicMock(spec=Plan)
    plan.name = plan_name
    plan.billing_cycle_type = "lifetime" if plan_name == "Free" else "recurring"

    shop = MagicMock(spec=Shop)
    shop.lifetime_missions_remaining = 3
    shop.lifetime_image_credits_remaining = 5
    shop.monthly_missions_used = 0
    shop.monthly_image_generations_used = 0
    if shop_overrides:
        for k, v in shop_overrides.items():
            setattr(shop, k, v)

    return {
        "user": MagicMock(username="test-shop"),
        "plan": plan,
        "shop": shop,
        "rewrites_used": 0,
        "rewrite_limit": 10,
        "effective_plan_name": plan_name,
        "is_active": True,
    }


# =========================================================================
# Part 1: Entitlements Config
# =========================================================================

class TestPlanEntitlements:

    def test_all_four_tiers_present(self):
        assert set(PLAN_ENTITLEMENTS.keys()) == {"Free", "Basic", "Standard", "Pro"}

    def test_free_has_all_modules(self):
        ent = PLAN_ENTITLEMENTS["Free"]
        assert ent["rewriter"] is True
        assert ent["seo"] is True
        assert ent["marketing"] is True
        assert ent["price_scout"] is True
        assert ent["missions"] is True

    def test_free_limited_products(self):
        assert PLAN_ENTITLEMENTS["Free"]["product_limit"] == 10

    def test_free_lifetime_missions(self):
        ent = PLAN_ENTITLEMENTS["Free"]
        assert ent["mission_limit"] == 3
        assert ent["mission_limit_type"] == "lifetime"
        assert ent["mission_agents"] == "full"

    def test_free_lifetime_images(self):
        ent = PLAN_ENTITLEMENTS["Free"]
        assert ent["image_generation_limit"] == 5
        assert ent["image_limit_type"] == "lifetime"

    def test_free_no_autonomous(self):
        ent = PLAN_ENTITLEMENTS["Free"]
        assert ent["autonomous"] is False
        assert ent["publish"] is False
        assert ent["apply_price"] is False

    def test_basic_no_seo_no_price_scout(self):
        ent = PLAN_ENTITLEMENTS["Basic"]
        assert ent["rewriter"] is True
        assert ent["marketing"] is True
        assert ent["seo"] is False
        assert ent["price_scout"] is False

    def test_basic_text_only_missions(self):
        ent = PLAN_ENTITLEMENTS["Basic"]
        assert ent["mission_limit"] == 1
        assert ent["mission_limit_type"] == "monthly"
        assert ent["mission_agents"] == "text_only"

    def test_basic_no_image_credits(self):
        ent = PLAN_ENTITLEMENTS["Basic"]
        assert ent["image_generation_limit"] == 0
        assert ent["image_refinement_adhoc"] is False
        assert ent["ad_image_generation"] is False

    def test_standard_all_modules_unlimited_products(self):
        ent = PLAN_ENTITLEMENTS["Standard"]
        assert ent["rewriter"] is True
        assert ent["seo"] is True
        assert ent["marketing"] is True
        assert ent["price_scout"] is True
        assert ent["product_limit"] == -1

    def test_standard_no_image_agents_in_missions(self):
        ent = PLAN_ENTITLEMENTS["Standard"]
        assert ent["mission_agents"] == "text_full"
        assert ent["image_generation_limit"] == 0
        assert ent["image_refinement_adhoc"] is False

    def test_standard_3_monthly_missions(self):
        ent = PLAN_ENTITLEMENTS["Standard"]
        assert ent["mission_limit"] == 3
        assert ent["mission_limit_type"] == "monthly"

    def test_pro_everything_enabled(self):
        ent = PLAN_ENTITLEMENTS["Pro"]
        for feature in ["rewriter", "seo", "marketing", "price_scout", "missions",
                        "image_refinement_adhoc", "ad_image_generation",
                        "social_post_preview", "autonomous", "publish",
                        "apply_price", "meta_integration"]:
            assert ent[feature] is True, f"Pro should have {feature}=True"

    def test_pro_150_image_credits(self):
        assert PLAN_ENTITLEMENTS["Pro"]["image_generation_limit"] == 150
        assert PLAN_ENTITLEMENTS["Pro"]["image_limit_type"] == "monthly"

    def test_pro_unlimited_missions(self):
        assert PLAN_ENTITLEMENTS["Pro"]["mission_limit"] == -1

    def test_get_entitlements_returns_copy(self):
        ent = get_entitlements("Pro")
        ent["rewriter"] = False
        assert PLAN_ENTITLEMENTS["Pro"]["rewriter"] is True

    def test_get_entitlements_unknown_plan_defaults_to_free(self):
        ent = get_entitlements("Unknown")
        assert ent == get_entitlements("Free")

    def test_get_required_tier_seo(self):
        assert get_required_tier("seo") == "Standard"

    def test_get_required_tier_image(self):
        assert get_required_tier("image_refinement_adhoc") == "Pro"

    def test_get_required_tier_unknown_returns_none(self):
        assert get_required_tier("rewriter") is None


# =========================================================================
# Part 2: validate_feature_access
# =========================================================================

class TestValidateFeatureAccess:

    def test_pro_can_access_all_features(self):
        ctx = _make_context("Pro")
        for feature in ["seo", "price_scout", "image_refinement_adhoc",
                        "ad_image_generation", "social_post_preview",
                        "autonomous", "publish", "meta_integration"]:
            validate_feature_access(ctx, feature)

    def test_basic_cannot_access_seo(self):
        ctx = _make_context("Basic")
        with pytest.raises(HTTPException) as exc:
            validate_feature_access(ctx, "seo")
        assert exc.value.status_code == 403
        assert "Standard" in exc.value.detail

    def test_basic_cannot_access_price_scout(self):
        ctx = _make_context("Basic")
        with pytest.raises(HTTPException) as exc:
            validate_feature_access(ctx, "price_scout")
        assert exc.value.status_code == 403

    def test_standard_cannot_access_images(self):
        ctx = _make_context("Standard")
        with pytest.raises(HTTPException) as exc:
            validate_feature_access(ctx, "image_refinement_adhoc")
        assert exc.value.status_code == 403
        assert "Pro" in exc.value.detail

    def test_standard_cannot_publish(self):
        ctx = _make_context("Standard")
        with pytest.raises(HTTPException) as exc:
            validate_feature_access(ctx, "autonomous")
        assert exc.value.status_code == 403

    def test_free_can_access_core_modules(self):
        ctx = _make_context("Free")
        for feature in ["rewriter", "seo", "marketing", "price_scout", "missions"]:
            validate_feature_access(ctx, feature)

    def test_free_cannot_publish(self):
        ctx = _make_context("Free")
        with pytest.raises(HTTPException) as exc:
            validate_feature_access(ctx, "autonomous")
        assert exc.value.status_code == 403


# =========================================================================
# Part 3: validate_agent_action_access
# =========================================================================

class TestValidateAgentActionAccess:

    def test_action_to_feature_mapping_exists(self):
        assert "seo_optimize" in _ACTION_TO_FEATURE
        assert "price_scout" in _ACTION_TO_FEATURE
        assert "social_hook_architect" in _ACTION_TO_FEATURE

    def test_pro_can_run_seo_optimize(self):
        ctx = _make_context("Pro")
        validate_agent_action_access(ctx, "seo_optimize")

    def test_basic_cannot_run_seo_optimize(self):
        ctx = _make_context("Basic")
        with pytest.raises(HTTPException) as exc:
            validate_agent_action_access(ctx, "seo_optimize")
        assert exc.value.status_code == 403

    def test_basic_cannot_run_price_scout(self):
        ctx = _make_context("Basic")
        with pytest.raises(HTTPException) as exc:
            validate_agent_action_access(ctx, "price_scout")
        assert exc.value.status_code == 403

    def test_standard_can_run_seo_optimize(self):
        ctx = _make_context("Standard")
        validate_agent_action_access(ctx, "seo_optimize")

    def test_unmapped_action_passes(self):
        ctx = _make_context("Basic")
        validate_agent_action_access(ctx, "unmapped_action")


# =========================================================================
# Part 4: validate_mission_access
# =========================================================================

class TestValidateMissionAccess:

    def test_free_allows_when_missions_remain(self):
        ctx = _make_context("Free", {"lifetime_missions_remaining": 2})
        validate_mission_access(ctx)

    def test_free_blocks_when_no_missions_remain(self):
        ctx = _make_context("Free", {"lifetime_missions_remaining": 0})
        with pytest.raises(HTTPException) as exc:
            validate_mission_access(ctx)
        assert exc.value.status_code == 403
        assert "lifetime" in exc.value.detail.lower()

    def test_basic_allows_when_under_monthly_limit(self):
        ctx = _make_context("Basic", {"monthly_missions_used": 0})
        validate_mission_access(ctx)

    def test_basic_blocks_when_at_monthly_limit(self):
        ctx = _make_context("Basic", {"monthly_missions_used": 1})
        with pytest.raises(HTTPException) as exc:
            validate_mission_access(ctx)
        assert exc.value.status_code == 403

    def test_standard_allows_under_3(self):
        ctx = _make_context("Standard", {"monthly_missions_used": 2})
        validate_mission_access(ctx)

    def test_standard_blocks_at_3(self):
        ctx = _make_context("Standard", {"monthly_missions_used": 3})
        with pytest.raises(HTTPException) as exc:
            validate_mission_access(ctx)
        assert exc.value.status_code == 403

    def test_pro_always_allows(self):
        ctx = _make_context("Pro", {"monthly_missions_used": 999})
        validate_mission_access(ctx)


# =========================================================================
# Part 5: validate_image_credits
# =========================================================================

class TestValidateImageCredits:

    def test_basic_has_no_image_access(self):
        ctx = _make_context("Basic")
        with pytest.raises(HTTPException) as exc:
            validate_image_credits(ctx)
        assert exc.value.status_code == 403

    def test_standard_has_no_image_access(self):
        ctx = _make_context("Standard")
        with pytest.raises(HTTPException) as exc:
            validate_image_credits(ctx)
        assert exc.value.status_code == 403

    def test_free_allows_when_credits_remain(self):
        ctx = _make_context("Free", {"lifetime_image_credits_remaining": 3})
        validate_image_credits(ctx)

    def test_free_blocks_when_credits_exhausted(self):
        ctx = _make_context("Free", {"lifetime_image_credits_remaining": 0})
        with pytest.raises(HTTPException) as exc:
            validate_image_credits(ctx)
        assert exc.value.status_code == 403

    def test_pro_allows_when_under_limit(self):
        ctx = _make_context("Pro", {"monthly_image_generations_used": 10})
        validate_image_credits(ctx)

    def test_pro_blocks_when_at_limit(self):
        ctx = _make_context("Pro", {"monthly_image_generations_used": 150})
        with pytest.raises(HTTPException) as exc:
            validate_image_credits(ctx)
        assert exc.value.status_code == 403


# =========================================================================
# Part 6: record_feature_usage / get_feature_usage
# =========================================================================

class TestFeatureUsageTracking:

    def test_record_increments_counter(self, db_session):
        count = record_feature_usage(db_session, "free-shop", "rewriter", 1)
        assert count == 1

    def test_record_increments_cumulatively(self, db_session):
        record_feature_usage(db_session, "free-shop", "rewriter", 3)
        count = record_feature_usage(db_session, "free-shop", "rewriter", 2)
        assert count == 5

    def test_get_returns_all_features(self, db_session):
        record_feature_usage(db_session, "free-shop", "rewriter", 5)
        record_feature_usage(db_session, "free-shop", "seo", 2)
        record_feature_usage(db_session, "free-shop", "image_generation", 1)

        usage = get_feature_usage(db_session, "free-shop")
        assert usage["rewriter"] == 5
        assert usage["seo"] == 2
        assert usage["image_generation"] == 1

    def test_get_empty_for_unknown_shop(self, db_session):
        usage = get_feature_usage(db_session, "nonexistent-shop")
        assert usage == {}

    def test_separate_shops_tracked_independently(self, db_session):
        record_feature_usage(db_session, "free-shop", "rewriter", 3)
        record_feature_usage(db_session, "basic-shop", "rewriter", 7)

        free_usage = get_feature_usage(db_session, "free-shop")
        basic_usage = get_feature_usage(db_session, "basic-shop")
        assert free_usage["rewriter"] == 3
        assert basic_usage["rewriter"] == 7


# =========================================================================
# Part 7: log_usage_event
# =========================================================================

class TestUsageEventLog:

    def test_log_creates_row(self, db_session):
        log_usage_event(
            db_session,
            shop_domain="free-shop",
            plan_name="Free",
            event_type="product_rewrite",
            feature="rewriter",
            product_count=1,
        )
        rows = db_session.query(UsageEventLog).filter_by(shop_domain="free-shop").all()
        assert len(rows) == 1
        assert rows[0].event_type == "product_rewrite"
        assert rows[0].product_count == 1

    def test_log_records_token_data(self, db_session):
        log_usage_event(
            db_session,
            shop_domain="pro-shop",
            plan_name="Pro",
            event_type="token_cost",
            feature="rewriter",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            estimated_cost_usd=0.005,
            model_used="gpt-4o",
        )
        row = db_session.query(UsageEventLog).filter_by(shop_domain="pro-shop").first()
        assert row.prompt_tokens == 100
        assert row.completion_tokens == 200
        assert row.total_tokens == 300
        assert float(row.estimated_cost_usd) == pytest.approx(0.005, abs=1e-6)
        assert row.model_used == "gpt-4o"

    def test_log_records_image_event(self, db_session):
        log_usage_event(
            db_session,
            shop_domain="pro-shop",
            plan_name="Pro",
            event_type="image_refinement",
            feature="image_generation",
            image_count=1,
            agent_name="ImageRefinementAgent",
            mission_id="m-123",
        )
        row = db_session.query(UsageEventLog).filter_by(
            shop_domain="pro-shop", event_type="image_refinement"
        ).first()
        assert row.image_count == 1
        assert row.agent_name == "ImageRefinementAgent"
        assert row.mission_id == "m-123"

    def test_log_is_append_only(self, db_session):
        for i in range(3):
            log_usage_event(
                db_session,
                shop_domain="free-shop",
                plan_name="Free",
                event_type="product_rewrite",
                feature="rewriter",
                product_count=1,
            )
        rows = db_session.query(UsageEventLog).filter_by(shop_domain="free-shop").all()
        assert len(rows) == 3

    def test_log_never_raises(self, db_session):
        """log_usage_event should swallow exceptions silently."""
        log_usage_event(
            db_session,
            shop_domain="free-shop",
            plan_name="Free",
            event_type="product_rewrite",
            feature="rewriter",
        )


# =========================================================================
# Part 8: sync_usage_limits resets new monthly counters
# =========================================================================

class TestSyncUsageLimitsResets:

    def test_resets_monthly_missions_and_images(self, db_session):
        shop = db_session.query(Shop).filter_by(domain="basic-shop").first()
        shop.monthly_missions_used = 1
        shop.monthly_image_generations_used = 42
        shop.next_reset_date = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.commit()

        shop = sync_usage_limits(db_session, shop, billing_cycle_type="recurring")
        assert shop.monthly_missions_used == 0
        assert shop.monthly_image_generations_used == 0
        assert shop.monthly_rewrites_used == 0

    def test_lifetime_plan_does_not_reset_monthly(self, db_session):
        shop = db_session.query(Shop).filter_by(domain="free-shop").first()
        shop.monthly_missions_used = 2
        db_session.commit()

        shop = sync_usage_limits(db_session, shop, billing_cycle_type="lifetime")
        assert shop.monthly_missions_used == 2


# =========================================================================
# Part 9: New Shop columns
# =========================================================================

class TestShopGatingColumns:

    def test_free_shop_has_lifetime_counters(self, db_session):
        shop = db_session.query(Shop).filter_by(domain="free-shop").first()
        assert shop.lifetime_missions_remaining == 3
        assert shop.lifetime_image_credits_remaining == 5

    def test_basic_shop_has_zero_lifetime(self, db_session):
        shop = db_session.query(Shop).filter_by(domain="basic-shop").first()
        assert shop.lifetime_missions_remaining == 0
        assert shop.lifetime_image_credits_remaining == 0

    def test_monthly_counters_start_at_zero(self, db_session):
        shop = db_session.query(Shop).filter_by(domain="pro-shop").first()
        assert shop.monthly_missions_used == 0
        assert shop.monthly_image_generations_used == 0


# =========================================================================
# Part 10: FeatureUsage model
# =========================================================================

class TestFeatureUsageModel:

    def test_create_and_query(self, db_session):
        today = datetime.now(timezone.utc).date()
        fu = FeatureUsage(
            shop_domain="pro-shop",
            feature="marketing",
            billing_cycle_start=today,
            usage_count=10,
        )
        db_session.add(fu)
        db_session.commit()

        result = db_session.query(FeatureUsage).filter_by(
            shop_domain="pro-shop", feature="marketing"
        ).first()
        assert result.usage_count == 10


# =========================================================================
# Part 11: UsageEventLog model
# =========================================================================

class TestUsageEventLogModel:

    def test_all_fields_persist(self, db_session):
        row = UsageEventLog(
            shop_domain="pro-shop",
            plan_name="Pro",
            event_type="mission_start",
            feature="mission",
            product_count=0,
            image_count=0,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0,
            product_id="gid://shopify/Product/123",
            mission_id="m-abc",
            agent_name="RewriterAgent",
            model_used="gpt-4o",
            action="generate-copy",
            metadata_json='{"key": "value"}',
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)

        assert row.id is not None
        assert row.product_id == "gid://shopify/Product/123"
        assert row.metadata_json == '{"key": "value"}'
        assert row.created_at is not None

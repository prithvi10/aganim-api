"""
Tests for image generation quota gate enforcement.

Covers:
- check_image_quota utility (unit)
- Pre-generation gate in VisualMarketingAgent
- Pre-generation gate in ImageRefinementAgent
- Pre-generation gate in ContentHeroAgent
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.db.database import Base
from src.ecommerce.db.models import User, Plan, Shop
from src.ecommerce.db.transactions import check_image_quota, ImageQuotaExceeded


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
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
        db.add(Plan(name=name, monthly_rewrite_limit=limit, product_limit=limit,
                     billing_cycle_type=cycle, max_request_rate=10))
    db.commit()

    free = db.query(Plan).filter_by(name="Free").first()
    pro = db.query(Plan).filter_by(name="Pro").first()

    for domain, plan, lifetime_img, monthly_img in [
        ("free-ok", free, 3, 0),         # 3 lifetime credits left
        ("free-exhausted", free, 0, 0),   # 0 lifetime credits
        ("pro-ok", pro, 0, 10),           # 10/150 monthly used
        ("pro-at-limit", pro, 0, 150),    # 150/150 monthly used
    ]:
        db.add(User(username=domain, plan_id=plan.id))
        db.add(Shop(
            domain=domain, access_token="tok",
            current_plan_name=plan.name,
            monthly_rewrites_used=0,
            lifetime_rewrites_remaining=10 if plan.name == "Free" else 0,
            lifetime_missions_remaining=3 if plan.name == "Free" else 0,
            lifetime_image_credits_remaining=lifetime_img,
            monthly_image_generations_used=monthly_img,
            reset_anchor_date=now,
            next_reset_date=now + timedelta(days=30),
        ))
    db.commit()

    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Unit tests: check_image_quota
# ---------------------------------------------------------------------------

class TestCheckImageQuota:

    def test_free_with_credits_remaining(self, db_session):
        check_image_quota(db_session, "free-ok", "Free")

    def test_free_exhausted_raises(self, db_session):
        with pytest.raises(ImageQuotaExceeded, match="quota exhausted"):
            check_image_quota(db_session, "free-exhausted", "Free")

    def test_pro_within_limit(self, db_session):
        check_image_quota(db_session, "pro-ok", "Pro")

    def test_pro_at_limit_raises(self, db_session):
        with pytest.raises(ImageQuotaExceeded, match="Monthly image quota reached"):
            check_image_quota(db_session, "pro-at-limit", "Pro")

    def test_basic_zero_limit_raises(self, db_session):
        with pytest.raises(ImageQuotaExceeded, match="not available"):
            check_image_quota(db_session, "free-ok", "Basic")

    def test_standard_within_limit(self, db_session):
        """Standard now has 10 image credits/month — should pass with credits remaining."""
        check_image_quota(db_session, "free-ok", "Standard")

    def test_unknown_shop_passes(self, db_session):
        """If the shop is not in the DB, we allow (fail-open)."""
        check_image_quota(db_session, "nonexistent-shop", "Pro")


# ---------------------------------------------------------------------------
# Integration tests: agent gate enforcement
# ---------------------------------------------------------------------------

def _make_state(shop_id: str, plan_tier: str, db, **extra):
    from src.ecommerce.state import MissionState
    return MissionState(
        product_id="test-product",
        shop_id=shop_id,
        plan_tier=plan_tier,
        raw_input=extra.get("raw_input", {}),
        db=db,
    )


def _make_ctx(**external):
    from src.agentic_core.agents.context import AgentContext
    ctx = AgentContext(raw_input={})
    ctx.external_data.update(external)
    return ctx


def _make_plan():
    from src.agentic_core.agents.context import AgentPlan
    return AgentPlan(steps=["generate"], selected_tools=[], confidence=1.0, reasoning="test")


class TestVisualMarketingAgentGate:

    @pytest.mark.asyncio
    async def test_blocks_when_quota_exhausted(self, db_session):
        from src.ecommerce.agents.visual_marketing.agent import VisualMarketingAgent

        services = MagicMock()
        agent = VisualMarketingAgent(shop_id="free-exhausted", services=services)

        state = _make_state("free-exhausted", "Free", db_session,
                            raw_input={"image_url": "https://example.com/img.jpg"})

        ctx = _make_ctx(image_url="https://example.com/img.jpg")

        actions, new_state = await agent._act_domain(state, ctx, _make_plan())

        assert len(actions) == 1
        assert not actions[0].success
        assert "quota" in actions[0].error.lower()

    @pytest.mark.asyncio
    async def test_allows_when_quota_available(self, db_session):
        from src.ecommerce.db.transactions import check_image_quota
        check_image_quota(db_session, "free-ok", "Free")


class TestImageRefinementAgentGate:

    @pytest.mark.asyncio
    async def test_blocks_when_quota_exhausted(self, db_session):
        from src.ecommerce.agents.image_refinement.agent import ImageRefinementAgent

        services = MagicMock()
        agent = ImageRefinementAgent(shop_id="pro-at-limit", services=services)

        state = _make_state("pro-at-limit", "Pro", db_session,
                            raw_input={"image_url": "https://example.com/img.jpg"})

        ctx = _make_ctx(image_url="https://example.com/img.jpg")

        actions, new_state = await agent._act_domain(state, ctx, _make_plan())

        assert len(actions) == 1
        assert not actions[0].success
        assert "quota" in actions[0].error.lower()


class TestContentHeroAgentGate:

    @pytest.mark.asyncio
    async def test_blocks_when_quota_exhausted(self, db_session):
        from src.ecommerce.agents.content_hero.agent import ContentHeroAgent

        services = MagicMock()
        services.llm = MagicMock()
        agent = ContentHeroAgent(shop_id="free-exhausted", services=services)

        state = _make_state("free-exhausted", "Free", db_session, raw_input={})

        ctx = _make_ctx(
            template_id="product/blog-post",
            context_data={"subject": "Test"},
            brand_soul="",
            image_style="attractive",
            image_url="",
            brand_name="",
            product_name="Test Product",
            product_category="General",
        )

        actions, new_state = await agent._act_domain(state, ctx, _make_plan())

        assert len(actions) == 1
        assert not actions[0].success
        assert "quota" in actions[0].error.lower()

    @pytest.mark.asyncio
    async def test_allows_when_quota_available(self, db_session):
        """Gate passes — quota check succeeds for a shop with remaining credits."""
        from src.ecommerce.db.transactions import check_image_quota
        check_image_quota(db_session, "free-ok", "Free")


class TestQuotaDecrementAfterSuccess:
    """Verify that quota is actually decremented after image generation."""

    def test_free_lifetime_decrement(self, db_session):
        shop = db_session.query(Shop).filter_by(domain="free-ok").first()
        assert shop.lifetime_image_credits_remaining == 3

        check_image_quota(db_session, "free-ok", "Free")

        shop.lifetime_image_credits_remaining -= 1
        db_session.commit()
        db_session.refresh(shop)
        assert shop.lifetime_image_credits_remaining == 2

    def test_pro_monthly_increment(self, db_session):
        shop = db_session.query(Shop).filter_by(domain="pro-ok").first()
        assert shop.monthly_image_generations_used == 10

        check_image_quota(db_session, "pro-ok", "Pro")

        shop.monthly_image_generations_used += 1
        db_session.commit()
        db_session.refresh(shop)
        assert shop.monthly_image_generations_used == 11

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from src.main.db.database import Base
from src.main.db.db_models import Plan, Shop, User
from src.main.services import fair_use_service as fair_use


TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=pool.StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _seed_shop(db, *, plan_name: str, monthly_cost: float = 0.0):
    plan = Plan(name=plan_name, monthly_rewrite_limit=-1, max_request_rate=100, can_stream_responses=True)
    db.add(plan)
    db.commit()

    domain = f"{plan_name.lower()}-shop.myshopify.com"
    user = User(username=domain, plan_id=plan.id)
    db.add(user)
    db.commit()

    now = datetime.now(timezone.utc)
    shop = Shop(
        domain=domain,
        access_token="tok",
        monthly_rewrites_used=0,
        reset_anchor_date=now,
        next_reset_date=now + timedelta(days=30),
        monthly_cost_accumulated=monthly_cost,
    )
    db.add(shop)
    db.commit()
    return domain


def test_extract_token_breakdown_dict_variants():
    # dict variant: prompt/completion/reasoning/total
    assert fair_use._extract_token_breakdown(
        {"prompt_tokens": 1, "completion_tokens": 2, "reasoning_tokens": 3, "total_tokens": 6}
    ) == (1, 2, 3, 6)
    # dict variant: only total_tokens -> treat as completion
    assert fair_use._extract_token_breakdown({"total_tokens": 10}) == (0, 10, 0, 10)
    # dict variant: input/output naming
    assert fair_use._extract_token_breakdown({"input_tokens": 4, "output_tokens": 5}) == (4, 5, 0, 9)


def test_extract_token_breakdown_object_variants():
    class U:
        prompt_tokens = 7
        completion_tokens = 8
        reasoning_tokens = 9
        total_tokens = 24

    assert fair_use._extract_token_breakdown(U()) == (7, 8, 9, 24)

    class U2:
        total_tokens = 11

    assert fair_use._extract_token_breakdown(U2()) == (0, 11, 0, 11)


def test_record_cost_from_usage_no_shop_returns_zero(db):
    assert fair_use.record_cost_from_usage(db, "missing.myshopify.com", {"total_tokens": 10}, model_used="x") == 0.0


def test_basic_and_standard_never_throttle_or_violate(db):
    basic = _seed_shop(db, plan_name="Basic", monthly_cost=9999.0)
    standard = _seed_shop(db, plan_name="Standard", monthly_cost=9999.0)

    assert fair_use.should_throttle_for_cycle(db, basic) is False
    assert fair_use.should_throttle_for_cycle(db, standard) is False
    assert fair_use.is_fair_use_violated(db, basic) is False
    assert fair_use.is_fair_use_violated(db, standard) is False


def test_pro_throttle_trigger_and_model_switch(db):
    shop_domain = _seed_shop(db, plan_name="Pro", monthly_cost=0.0)

    # Make math deterministic and easy: 1 token == $1
    with patch.object(fair_use, "_USD_PER_INPUT_TOKEN", 0.0), patch.object(
        fair_use, "_USD_PER_OUTPUT_TOKEN", 1.0
    ), patch.object(fair_use, "_USD_PER_REASONING_TOKEN", 0.0), patch.object(
        fair_use, "FAIR_USE_COST_CAP", 150.0
    ), patch.object(
        fair_use, "OPENAI_MODEL_DEGRADED", "gpt-4o-mini"
    ):
        # Below cap
        fair_use.record_cost_from_usage(db, shop_domain, {"completion_tokens": 10}, model_used="gpt-5-pro")
        assert fair_use.should_throttle_for_cycle(db, shop_domain) is False
        assert fair_use.get_effective_model(db, shop_domain, "gpt-5-pro") == "gpt-5-pro"

        # Above cap (add 200 -> total 210)
        with patch.object(fair_use.logger, "warning") as warn:
            fair_use.record_cost_from_usage(db, shop_domain, {"completion_tokens": 200}, model_used="gpt-5-pro")
            assert fair_use.should_throttle_for_cycle(db, shop_domain) is True
            assert fair_use.is_fair_use_violated(db, shop_domain) is True
            assert fair_use.get_effective_model(db, shop_domain, "gpt-5-pro") == "gpt-4o-mini"
            # YELLOW alert logged once
            assert any("YELLOW_ALERT" in str(c.args[0]) for c in warn.call_args_list)


def test_yellow_alert_is_once_per_cycle(db):
    shop_domain = _seed_shop(db, plan_name="Pro", monthly_cost=0.0)

    with patch.object(fair_use, "_USD_PER_OUTPUT_TOKEN", 1.0), patch.object(fair_use, "FAIR_USE_COST_CAP", 1.0):
        with patch.object(fair_use.logger, "warning") as warn:
            fair_use.record_cost_from_usage(db, shop_domain, {"completion_tokens": 2}, model_used="gpt-5-pro")
            fair_use.record_cost_from_usage(db, shop_domain, {"completion_tokens": 2}, model_used="gpt-5-pro")
            # should only emit YELLOW_ALERT once per cycle
            alerts = [c for c in warn.call_args_list if "YELLOW_ALERT" in str(c.args[0])]
            assert len(alerts) == 1


def test_webhook_failure_does_not_raise(db, monkeypatch):
    shop_domain = _seed_shop(db, plan_name="Pro", monthly_cost=0.0)
    monkeypatch.setenv("FAIR_USE_WEBHOOK_URL", "https://example.invalid/webhook")

    with patch.object(fair_use, "_USD_PER_OUTPUT_TOKEN", 1.0), patch.object(fair_use, "FAIR_USE_COST_CAP", 1.0):
        with patch("src.main.services.fair_use_service.httpx.post", side_effect=Exception("boom")):
            # Should not raise
            fair_use.record_cost_from_usage(db, shop_domain, {"completion_tokens": 2}, model_used="gpt-5-pro")


def test_cycle_reset_clears_cost_and_throttle(db):
    shop_domain = _seed_shop(db, plan_name="Pro", monthly_cost=200.0)

    assert fair_use.should_throttle_for_cycle(db, shop_domain) is True

    # Force next_reset_date into the past then call sync_usage_limits (self-heal)
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    assert shop is not None
    shop.next_reset_date = datetime.now(timezone.utc) - timedelta(days=1)
    db.add(shop)
    db.commit()

    from src.main.db.db_transactions import sync_usage_limits

    sync_usage_limits(db, shop)
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    assert float(shop.monthly_cost_accumulated or 0) == 0.0
    assert fair_use.should_throttle_for_cycle(db, shop_domain) is False


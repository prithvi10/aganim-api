"""Tests for the shop-level brand_soul_enabled toggle."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Tuple

from src.agentic_core.agents.base import BaseAgent
from src.ecommerce.state import ShopifyMissionState as MissionState
from src.agentic_core.agents.context import AgentContext, AgentPlan, AgentAction
from src.ecommerce.core.generation import _should_use_brand_context


# =============================================================================
# Minimal concrete agent for testing BaseAgent.perceive()
# =============================================================================

class StubAgent(BaseAgent):
    """Bare-minimum agent that passes context/state through unchanged."""

    role_name = "StubAgent"
    default_tool = "stub.tool"

    async def _perceive_domain(self, state, context):
        return context

    async def _act_domain(self, state, context, plan):
        return [AgentAction.success_action("stub.tool", "ok")], state

    async def _feedback_domain(self, old_state, new_state, actions):
        pass

    async def _reason_domain(self, state, context):
        return self._create_default_plan(state, context)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for testing."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value='{"title": "Test"}')
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=[])
    services.rag.get_strategic_intelligence = AsyncMock(return_value={
        "archetype": "Artisan",
        "tonal_guardrails": {"formality_level": "elevated"},
        "power_words": ["heritage", "craft"],
        "banned_phrases": ["cheap"],
        "core_value_props": ["Handmade in Kyoto"],
        "cultural_touchpoints": ["Wabi-sabi"],
        "linguistic_rules": {"sentence_style": "flowing"},
    })
    services.publish_adapter.get_credentials = AsyncMock(return_value={})
    return services


# =============================================================================
# Tests: _should_use_brand_context (generation.py)
# =============================================================================

class TestShouldUseBrandContext:
    """Tests for the _should_use_brand_context helper in generation.py."""

    def test_shop_toggle_off_overrides_everything(self):
        """shop_toggle=False → False, regardless of plan or requested flag."""
        assert _should_use_brand_context("Pro", True, shop_toggle=False) is False
        assert _should_use_brand_context("Standard", True, shop_toggle=False) is False

    def test_shop_toggle_on_with_pro_plan(self):
        """shop_toggle=True + Pro plan + requested → True."""
        assert _should_use_brand_context("Pro", True, shop_toggle=True) is True

    def test_shop_toggle_on_with_standard_plan(self):
        """shop_toggle=True + Standard plan + requested → True."""
        assert _should_use_brand_context("Standard", True, shop_toggle=True) is True

    def test_shop_toggle_none_defaults_to_old_behavior(self):
        """shop_toggle=None preserves legacy behaviour (no gating on toggle)."""
        assert _should_use_brand_context("Pro", True, shop_toggle=None) is True
        assert _should_use_brand_context("Pro", False, shop_toggle=None) is False
        assert _should_use_brand_context("Basic", True, shop_toggle=None) is False

    def test_shop_toggle_on_but_not_requested(self):
        """Even with toggle on, requested=False still prevents brand context."""
        assert _should_use_brand_context("Pro", False, shop_toggle=True) is False

    def test_shop_toggle_on_basic_plan(self):
        """Basic plan never gets brand context regardless of toggle."""
        assert _should_use_brand_context("Basic", True, shop_toggle=True) is False


# =============================================================================
# Tests: BaseAgent.perceive() brand_soul_enabled gating
# =============================================================================

@pytest.mark.asyncio
async def test_perceive_with_brand_soul_enabled_true(mock_services):
    """brand_soul_enabled=True → strategic_intelligence is populated."""
    state = MissionState(
        product_id="p-1",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"brand_soul_enabled": True, "title": "Bowl"},
        db=MagicMock(),
    )

    agent = StubAgent("shop.myshopify.com", mock_services)
    agent.memory.get_learned_preferences = AsyncMock(return_value=[])

    context = await agent.perceive(state)

    mock_services.rag.get_strategic_intelligence.assert_awaited_once()
    assert context.strategic_intelligence is not None
    assert context.strategic_intelligence["archetype"] == "Artisan"


@pytest.mark.asyncio
async def test_perceive_with_brand_soul_disabled(mock_services):
    """brand_soul_enabled=False → strategic_intelligence is None, RAG not called."""
    state = MissionState(
        product_id="p-2",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"brand_soul_enabled": False, "title": "Bowl"},
        db=MagicMock(),
    )

    agent = StubAgent("shop.myshopify.com", mock_services)
    agent.memory.get_learned_preferences = AsyncMock(return_value=[])

    context = await agent.perceive(state)

    mock_services.rag.get_strategic_intelligence.assert_not_awaited()
    assert context.strategic_intelligence is None


@pytest.mark.asyncio
async def test_perceive_default_loads_brand_soul(mock_services):
    """No brand_soul_enabled key in raw_input → defaults to True (backward compat)."""
    state = MissionState(
        product_id="p-3",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"title": "Bowl"},
        db=MagicMock(),
    )

    agent = StubAgent("shop.myshopify.com", mock_services)
    agent.memory.get_learned_preferences = AsyncMock(return_value=[])

    context = await agent.perceive(state)

    mock_services.rag.get_strategic_intelligence.assert_awaited_once()
    assert context.strategic_intelligence is not None

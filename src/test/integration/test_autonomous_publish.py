"""
Integration tests for the Autonomous Publish flow.

Tests the end-to-end flow from MissionControl → Agent → _maybe_publish,
verifying that Pro tier triggers publishing and non-Pro does not.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.main.agents.orchestrator import MissionControl
from src.main.agents.state import MissionState
from src.main.agents.rewriter import RewriterAgent
from src.main.agents.seo import SEOAgent
from src.main.agents.marketing import MarketingAgent
from src.main.agents.price_scout import PriceScoutAgent
from src.main.services.meta_service import MetaService

CopywriterAgent = RewriterAgent


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry for integration testing."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value='{"title": "Test", "description": "Test desc"}')
    services.llm.generate_structured = AsyncMock(return_value=MagicMock(
        model_dump=lambda: {"has_violations": False, "flags": [], "severity": "none"},
        has_violations=False,
        flags=[],
        severity="none",
    ))
    services.llm.generate_json = AsyncMock(return_value={})
    services.serp.search = AsyncMock(return_value=[])
    services.serp.get_competitor_prices = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=[])
    services.meta = MagicMock(spec=MetaService)
    services.meta.post_ad = AsyncMock(return_value=(True, "post_id_123"))
    return services


@pytest.fixture
def pro_state():
    """Create a Pro-tier MissionState for integration testing."""
    return MissionState(
        product_id="product-123",
        shop_id="pro-shop.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "description": "Made in Kyoto using traditional techniques.",
            "category": "Kitchenware",
        },
        target_locale="en",
    )


@pytest.fixture
def standard_state():
    """Create a Standard-tier MissionState for integration testing."""
    return MissionState(
        product_id="product-456",
        shop_id="standard-shop.myshopify.com",
        plan_tier="Standard",
        raw_input={
            "title": "Test Product",
            "description": "Test description.",
            "category": "General",
        },
    )


# =============================================================================
# Integration: Pro tier mission sets autonomous=True on state
# =============================================================================

@pytest.mark.asyncio
async def test_pro_mission_full_workflow_sets_autonomous(mock_services, pro_state):
    """Test that a Pro tier full mission sets autonomous=True on state throughout."""
    mission = MissionControl(
        plan_tier="Pro",
        shop_id="pro-shop.myshopify.com",
        services=mock_services,
    )

    states = []
    async for state in mission.execute(pro_state):
        states.append(state)
        assert state.autonomous is True, f"State should have autonomous=True, got {state.autonomous}"

    # Final state should be COMPLETED
    assert states[-1].status == "COMPLETED"


@pytest.mark.asyncio
async def test_standard_mission_keeps_autonomous_false(mock_services, standard_state):
    """Test that Standard tier mission keeps autonomous=False."""
    mission = MissionControl(
        plan_tier="Standard",
        shop_id="standard-shop.myshopify.com",
        services=mock_services,
    )

    states = []
    async for state in mission.execute(standard_state):
        states.append(state)
        assert state.autonomous is False

    assert states[-1].status == "COMPLETED"


# =============================================================================
# Integration: Step-by-step with publish on approval
# =============================================================================

@pytest.mark.asyncio
async def test_step_by_step_publish_on_approval(mock_services, pro_state):
    """
    Integration test: step-by-step execution with a template_id.
    When the step is approved (advance_to_next_step), _maybe_publish is called.
    """
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True, "template_id": "product/description"},
        {"agent_name": "SEOAgent", "has_gate": True},
    ]
    pro_state.workflow_config = config

    async def mock_rewriter_run(self, state):
        state.draft_content = "<p>Beautiful ceramic bowl crafted in Kyoto.</p>"
        state.draft_title = "Handcrafted Ceramic Bowl"
        state.add_log(f"{self.role_name}: Generated content")
        return state

    async def mock_seo_run(self, state):
        state.seo_title = "Best Ceramic Bowl"
        return state

    with patch.object(CopywriterAgent, 'run', mock_rewriter_run), \
         patch.object(SEOAgent, 'run', mock_seo_run):

        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )

        # Step 1: Run the first agent (RewriterAgent)
        states = []
        async for state in mission.execute_single_step(pro_state):
            states.append(state)

        final_state = states[-1]
        assert final_state.status == "AWAITING_APPROVAL"
        assert final_state.draft_content is not None

        # Step 2: Approve step (simulates "Continue" click)
        # This should trigger _on_step_approved → _maybe_publish
        with patch.object(RewriterAgent, '_maybe_publish', new_callable=AsyncMock, return_value=(True, None)) as mock_pub:
            result = await mission.advance_to_next_step(final_state)

            # _maybe_publish should have been called
            mock_pub.assert_called_once()
            template_id_arg = mock_pub.call_args[0][1]  # Second positional arg
            assert template_id_arg == "product/description"

            # State should have advanced
            assert result.current_agent_index == 1


@pytest.mark.asyncio
async def test_step_by_step_no_publish_for_standard(mock_services, standard_state):
    """Test that Standard tier step approval does NOT call _maybe_publish."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True, "template_id": "product/description"},
    ]
    standard_state.workflow_config = config

    async def mock_run(self, state):
        state.draft_content = "Content"
        return state

    with patch.object(CopywriterAgent, 'run', mock_run):
        mission = MissionControl(
            plan_tier="Standard",
            shop_id="standard-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )

        states = []
        async for state in mission.execute_single_step(standard_state):
            states.append(state)

        final_state = states[-1]
        assert final_state.status == "AWAITING_APPROVAL"

        with patch.object(RewriterAgent, '_maybe_publish', new_callable=AsyncMock) as mock_pub:
            result = await mission.advance_to_next_step(final_state)
            mock_pub.assert_not_called()


# =============================================================================
# Integration: Auto-proceed with publish
# =============================================================================

@pytest.mark.asyncio
async def test_auto_proceed_step_also_publishes(mock_services, pro_state):
    """Test that auto-proceed (has_gate=False) on Pro still calls _on_step_approved."""
    config = [
        {"agent_name": "MarketingAgent", "has_gate": False, "template_id": "marketing/ad-facebook"},
        {"agent_name": "SEOAgent", "has_gate": True},
    ]
    pro_state.workflow_config = config

    async def mock_marketing_run(self, state):
        state.draft_content = "Amazing product caption!"
        return state

    with patch.object(MarketingAgent, 'run', mock_marketing_run):
        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
            workflow_config=config,
        )

        with patch.object(MarketingAgent, '_maybe_publish', new_callable=AsyncMock, return_value=(True, None)) as mock_pub:
            states = []
            async for state in mission.execute_single_step(pro_state):
                states.append(state)

            # On auto-proceed, _maybe_publish should still be called
            mock_pub.assert_called_once()

        final_state = states[-1]
        # Should have auto-advanced
        assert final_state.current_agent_index == 1


# =============================================================================
# Integration: PriceScout autonomous with guardrails
# =============================================================================

@pytest.mark.asyncio
async def test_price_scout_publish_respects_guardrails():
    """Test that PriceScoutAgent._maybe_publish validates against price guardrails."""
    mock_services = MagicMock()

    state = MissionState(
        product_id="product-123",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"variant_id": "variant_789"},
        autonomous=True,
    )
    state.pricing_analysis = {"recommended_price": 999.99, "confidence": 0.9}

    # Mock DB with guardrails that reject the price
    mock_db = MagicMock()
    state.db = mock_db

    with patch('src.main.services.shopify_service.get_shop_credentials', return_value={
        "access_token": "shpat_test",
        "price_guardrails": {"min_price": 10, "max_price": 100},
    }):
        agent = PriceScoutAgent("shop.myshopify.com", services=mock_services)
        is_published, error = await agent._maybe_publish(state, "product/price-update")

    assert is_published is False
    assert error == "price_outside_guardrails"


@pytest.mark.asyncio
async def test_price_scout_publish_succeeds_within_guardrails():
    """Test that PriceScoutAgent publishes when price is within guardrails."""
    mock_services = MagicMock()

    state = MissionState(
        product_id="product-123",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"variant_id": "variant_789"},
        autonomous=True,
    )
    state.pricing_analysis = {"recommended_price": 49.99, "confidence": 0.9}

    mock_db = MagicMock()
    state.db = mock_db

    with patch('src.main.services.shopify_service.get_shop_credentials', return_value={
        "access_token": "shpat_test",
        "price_guardrails": {"min_price": 10, "max_price": 100},
    }), patch('src.main.services.shopify_service.update_variant_price', new_callable=AsyncMock) as mock_update:
        agent = PriceScoutAgent("shop.myshopify.com", services=mock_services)
        is_published, error = await agent._maybe_publish(state, "product/price-update")

    assert is_published is True
    assert error is None
    mock_update.assert_called_once()


# =============================================================================
# Integration: RewriterAgent publish handlers
# =============================================================================

@pytest.mark.asyncio
async def test_rewriter_publish_product_body():
    """Test RewriterAgent publishes product body for product/description template."""
    mock_services = MagicMock()

    state = MissionState(
        product_id="product-123",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"template_id": "product/description"},
        autonomous=True,
    )
    state.draft_content = "<p>Beautiful handcrafted ceramic bowl.</p>"

    mock_db = MagicMock()
    state.db = mock_db

    with patch('src.main.services.shopify_service.get_shop_credentials', return_value={
        "access_token": "shpat_test",
    }), patch('src.main.services.shopify_service.update_product_body', new_callable=AsyncMock) as mock_update:
        agent = RewriterAgent("shop.myshopify.com", services=mock_services)
        is_published, error = await agent._maybe_publish(state, "product/description")

    assert is_published is True
    assert error is None
    mock_update.assert_called_once_with(
        shop_domain="shop.myshopify.com",
        access_token="shpat_test",
        product_id="product-123",
        html="<p>Beautiful handcrafted ceramic bowl.</p>",
    )


@pytest.mark.asyncio
async def test_rewriter_publish_faq_appends_to_body():
    """Test RewriterAgent appends FAQ HTML to product description body."""
    mock_services = MagicMock()

    state = MissionState(
        product_id="product-123",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"template_id": "product/faq"},
        autonomous=True,
    )
    state.draft_content = '{"faqs": [{"question": "What is it?", "answer": "A ceramic bowl."}]}'

    mock_db = MagicMock()
    state.db = mock_db

    with patch('src.main.services.shopify_service.get_shop_credentials', return_value={
        "access_token": "shpat_test",
    }), \
    patch('src.main.services.shopify_service.get_product_body', new_callable=AsyncMock, return_value="<p>Existing desc</p>") as mock_get, \
    patch('src.main.services.shopify_service.update_product_body', new_callable=AsyncMock) as mock_update:
        agent = RewriterAgent("shop.myshopify.com", services=mock_services)
        is_published, error = await agent._maybe_publish(state, "product/faq")

    assert is_published is True
    assert error is None
    mock_get.assert_called_once()
    mock_update.assert_called_once()
    # Verify FAQ HTML was appended (body should contain both existing desc and FAQ markers)
    saved_html = mock_update.call_args.kwargs["html"]
    assert "<p>Existing desc</p>" in saved_html
    assert "<!-- cba-faq-start -->" in saved_html
    assert "What is it?" in saved_html
    assert "A ceramic bowl." in saved_html
    assert "<!-- cba-faq-end -->" in saved_html


# =============================================================================
# Integration: MarketingAgent publish handlers
# =============================================================================

@pytest.mark.asyncio
async def test_marketing_publish_flow_event():
    """Test MarketingAgent publishes email content via Shopify Flow."""
    mock_services = MagicMock()

    state = MissionState(
        product_id="product-123",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"template_id": "marketing/email-launch"},
        autonomous=True,
    )
    state.draft_content = "Welcome to our new product launch!"

    mock_db = MagicMock()
    state.db = mock_db

    with patch('src.main.services.shopify_service.get_shop_credentials', return_value={
        "access_token": "shpat_test",
    }), patch('src.main.services.shopify_service.trigger_flow_event', new_callable=AsyncMock) as mock_trigger:
        agent = MarketingAgent("shop.myshopify.com", services=mock_services)
        is_published, error = await agent._maybe_publish(state, "marketing/email-launch")

    assert is_published is True
    assert error is None
    mock_trigger.assert_called_once()


@pytest.mark.asyncio
async def test_marketing_publish_meta_ad():
    """Test MarketingAgent publishes ad via Meta Graph API."""
    mock_meta = MagicMock(spec=MetaService)
    mock_meta.post_ad = AsyncMock(return_value=(True, "post_99"))

    mock_services = MagicMock()
    mock_services.meta = mock_meta

    state = MissionState(
        product_id="product-123",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"template_id": "marketing/ad-facebook", "image_url": "https://cdn.shopify.com/img.jpg"},
        autonomous=True,
    )
    state.draft_content = "Shop our new arrivals! Limited time only."

    mock_db = MagicMock()
    state.db = mock_db

    with patch('src.main.services.shopify_service.get_shop_credentials', return_value={
        "access_token": "shpat_test",
        "meta_access_token": "EAA_token",
        "meta_page_id": "page_123",
    }):
        agent = MarketingAgent("shop.myshopify.com", services=mock_services)
        is_published, error = await agent._maybe_publish(state, "marketing/ad-facebook")

    assert is_published is True
    assert error is None
    mock_meta.post_ad.assert_called_once()
    call_kwargs = mock_meta.post_ad.call_args.kwargs
    assert call_kwargs["page_id"] == "page_123"
    assert call_kwargs["access_token"] == "EAA_token"


@pytest.mark.asyncio
async def test_marketing_meta_ad_fails_without_credentials():
    """Test that MarketingAgent Meta ad fails without Meta credentials."""
    mock_services = MagicMock()
    mock_services.meta = MagicMock(spec=MetaService)

    state = MissionState(
        product_id="product-123",
        shop_id="shop.myshopify.com",
        plan_tier="Pro",
        raw_input={"template_id": "marketing/ad-google"},
        autonomous=True,
    )
    state.draft_content = "Ad copy"

    mock_db = MagicMock()
    state.db = mock_db

    with patch('src.main.services.shopify_service.get_shop_credentials', return_value={
        "access_token": "shpat_test",
        "meta_access_token": None,
        "meta_page_id": None,
    }):
        agent = MarketingAgent("shop.myshopify.com", services=mock_services)
        is_published, error = await agent._maybe_publish(state, "marketing/ad-google")

    assert is_published is False
    assert "meta_credentials_missing" in error


# =============================================================================
# Integration: _on_step_approved injects is_published into agent_outputs
# =============================================================================

@pytest.mark.asyncio
async def test_on_step_approved_injects_is_published_in_outputs(mock_services, pro_state):
    """Test that _on_step_approved sets is_published in agent_outputs."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True, "template_id": "product/description"},
    ]
    pro_state.autonomous = True
    pro_state.workflow_config = config
    pro_state.agent_outputs["RewriterAgent:product/description"] = {
        "template_id": "product/description",
        "draft_content": "<p>Content</p>",
    }

    mission = MissionControl(
        plan_tier="Pro",
        shop_id="pro-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )

    with patch.object(RewriterAgent, '_maybe_publish', new_callable=AsyncMock, return_value=(True, None)):
        await mission._on_step_approved(pro_state, 0)

    output = pro_state.agent_outputs["RewriterAgent:product/description"]
    assert output["is_published"] is True
    assert "publish_error" not in output


@pytest.mark.asyncio
async def test_on_step_approved_injects_publish_error_on_failure(mock_services, pro_state):
    """Test that _on_step_approved records publish_error in agent_outputs on failure."""
    config = [
        {"agent_name": "RewriterAgent", "has_gate": True, "template_id": "product/blog-post"},
    ]
    pro_state.autonomous = True
    pro_state.workflow_config = config
    pro_state.agent_outputs["RewriterAgent:product/blog-post"] = {"draft_content": "Blog"}

    mission = MissionControl(
        plan_tier="Pro",
        shop_id="pro-shop.myshopify.com",
        services=mock_services,
        workflow_config=config,
    )

    with patch.object(RewriterAgent, '_maybe_publish', new_callable=AsyncMock, return_value=(False, "blog_id required")):
        await mission._on_step_approved(pro_state, 0)

    output = pro_state.agent_outputs["RewriterAgent:product/blog-post"]
    assert output["is_published"] is False
    assert output["publish_error"] == "blog_id required"


# =============================================================================
# Integration: End-to-end autonomous workflow (full pipeline)
# =============================================================================

@pytest.mark.asyncio
async def test_full_pipeline_pro_tier_autonomous_flag_persists(mock_services, pro_state):
    """Test that autonomous flag persists through the entire agent pipeline."""
    captured_flags = []

    async def capture_autonomous(self, state):
        captured_flags.append(state.autonomous)
        state.add_log(f"{self.role_name}: ran")
        return state

    with patch.object(CopywriterAgent, 'run', capture_autonomous), \
         patch.object(SEOAgent, 'run', capture_autonomous), \
         patch.object(MarketingAgent, 'run', capture_autonomous), \
         patch.object(PriceScoutAgent, 'run', capture_autonomous):

        mission = MissionControl(
            plan_tier="Pro",
            shop_id="pro-shop.myshopify.com",
            services=mock_services,
        )

        states = []
        async for state in mission.execute(pro_state):
            states.append(state)

    # All 4 agents should have seen autonomous=True
    assert len(captured_flags) == 4
    assert all(f is True for f in captured_flags)

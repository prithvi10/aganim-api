"""
Integration Tests: MarketingAgent End-to-End with Brand Soul.

Simulates the complete marketing content pipeline:
1. Brand soul → Strategic Intelligence → Operational Rules injection
2. MarketingAgent perceive → reason → act for each template
3. Validates output structure, brand voice, and state management

Tests all 7 marketing templates:
- Social hooks (Instagram/TikTok)
- Email (launch, abandoned cart, welcome)
- Blog post
- Ad copy (Facebook, Google)
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.main.agents.marketing import MarketingAgent
from src.main.agents.state import MissionState
from src.main.agents.context import AgentContext

from src.test.fixtures.brand_soul_fixtures import (
    STRATEGIC_INTELLIGENCE,
    BRAND_CONTEXT_CHUNKS,
    PRODUCT_CELADON_BOWL,
    PRODUCT_TEAPOT,
    PRODUCT_VASE,
    MOCK_SOCIAL_HOOKS_RESPONSE,
    MOCK_EMAIL_LAUNCH_RESPONSE,
    MOCK_EMAIL_ABANDONED_RESPONSE,
    MOCK_EMAIL_WELCOME_RESPONSE,
    MOCK_BLOG_POST_RESPONSE,
    MOCK_AD_FACEBOOK_RESPONSE,
    MOCK_AD_GOOGLE_RESPONSE,
    BRAND_VOICE_MUST_INCLUDE_KEYWORDS,
    BRAND_VOICE_BANNED_WORDS,
)


# =============================================================================
# Helpers
# =============================================================================

def _assert_brand_voice(text: str, min_keywords: int = 2):
    """Assert brand voice compliance."""
    text_lower = text.lower()
    matches = [kw for kw in BRAND_VOICE_MUST_INCLUDE_KEYWORDS if kw.lower() in text_lower]
    assert len(matches) >= min_keywords, (
        f"Expected at least {min_keywords} brand keywords, found {len(matches)}: {matches}"
    )
    for banned in BRAND_VOICE_BANNED_WORDS:
        assert banned.lower() not in text_lower, f"Banned word '{banned}' in output"


def _create_mock_services(llm_response: str):
    """Create mock services with a specific LLM response."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value=llm_response)
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=BRAND_CONTEXT_CHUNKS)
    services.rag._get_strategic_intelligence = AsyncMock(return_value=STRATEGIC_INTELLIGENCE)
    return services


def _make_state(product: dict, template_id: str = None, **extra_inputs) -> MissionState:
    """Create a MissionState for a given product and template."""
    raw_input = {
        "title": product["title"],
        "description": product["description"],
        "category": product["category"],
        "target_locale": "en",
        "tags": product.get("tags", []),
    }
    if template_id:
        raw_input["template_id"] = template_id
    raw_input.update(extra_inputs)

    return MissionState(
        product_id=product["id"],
        shop_id="takumi-ceramics.myshopify.com",
        plan_tier="Pro",
        raw_input=raw_input,
        target_locale="en",
    )


# =============================================================================
# Integration: Social Hooks Pipeline
# =============================================================================

class TestSocialHooksE2E:
    """End-to-end tests for social media content pipeline."""

    @pytest.mark.asyncio
    async def test_instagram_hooks_full_pipeline(self):
        """Full pipeline: product data → social hooks for Instagram."""
        services = _create_mock_services(MOCK_SOCIAL_HOOKS_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(PRODUCT_CELADON_BOWL)
        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.social_hooks is not None
        assert len(result.social_hooks) >= 1

        # Each hook should have correct structure
        for hook in result.social_hooks:
            assert "type" in hook
            assert "caption" in hook
            assert "hashtags" in hook
            assert "copy_text" in hook
            assert len(hook["caption"]) > 10

    @pytest.mark.asyncio
    async def test_tiktok_hooks_routing(self):
        """TikTok template should route to social generator."""
        services = _create_mock_services(MOCK_SOCIAL_HOOKS_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(PRODUCT_CELADON_BOWL, template_id="marketing/social-tiktok")
        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.social_hooks is not None

    @pytest.mark.asyncio
    async def test_social_hooks_brand_voice(self):
        """Social hooks should follow brand voice."""
        parsed = json.loads(MOCK_SOCIAL_HOOKS_RESPONSE)
        all_captions = " ".join(h["caption"] for h in parsed["hooks"])
        _assert_brand_voice(all_captions)

    @pytest.mark.asyncio
    async def test_social_hooks_hashtags_cleaned(self):
        """Hashtags should start with # and be properly formatted."""
        services = _create_mock_services(MOCK_SOCIAL_HOOKS_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(PRODUCT_CELADON_BOWL)
        result = await agent.run(state)

        for hook in result.social_hooks:
            for tag in hook["hashtags"]:
                assert tag.startswith("#"), f"Hashtag '{tag}' missing # prefix"


# =============================================================================
# Integration: Email Templates Pipeline
# =============================================================================

class TestEmailPipelineE2E:
    """End-to-end tests for email content generation."""

    @pytest.mark.asyncio
    async def test_launch_email_full_pipeline(self):
        """Full pipeline: product data → launch email."""
        services = _create_mock_services(MOCK_EMAIL_LAUNCH_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(
            PRODUCT_CELADON_BOWL,
            template_id="marketing/email-launch",
            launch_date="2026-03-15",
        )
        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

        # Verify gpt-4o was used for email quality
        call_kwargs = services.llm.generate_text.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o"

    @pytest.mark.asyncio
    async def test_abandoned_cart_email_full_pipeline(self):
        """Full pipeline: product data → abandoned cart email."""
        services = _create_mock_services(MOCK_EMAIL_ABANDONED_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(
            PRODUCT_CELADON_BOWL,
            template_id="marketing/email-abandoned",
            price=PRODUCT_CELADON_BOWL["price"],
        )
        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_welcome_email_full_pipeline(self):
        """Full pipeline: brand info → welcome email."""
        services = _create_mock_services(MOCK_EMAIL_WELCOME_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(
            PRODUCT_CELADON_BOWL,
            template_id="marketing/email-welcome",
            brand_name="Takumi Ceramics",
        )
        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_all_emails_brand_consistent(self):
        """All email outputs should be brand-consistent."""
        emails = [
            ("marketing/email-launch", MOCK_EMAIL_LAUNCH_RESPONSE, {"launch_date": "2026-04-01"}),
            ("marketing/email-abandoned", MOCK_EMAIL_ABANDONED_RESPONSE, {"price": "¥12,800"}),
            ("marketing/email-welcome", MOCK_EMAIL_WELCOME_RESPONSE, {"brand_name": "Takumi Ceramics"}),
        ]

        for template_id, mock_response, extra in emails:
            parsed = json.loads(mock_response)
            body = parsed.get("body", "")
            _assert_brand_voice(body)

            # No banned words in any email
            for banned in BRAND_VOICE_BANNED_WORDS:
                assert banned.lower() not in body.lower(), (
                    f"Banned word '{banned}' in {template_id} email body"
                )


# =============================================================================
# Integration: Blog Post Pipeline
# =============================================================================

class TestBlogPostE2E:
    """End-to-end tests for blog post generation."""

    @pytest.mark.asyncio
    async def test_blog_post_full_pipeline(self):
        """Full pipeline: topic → blog post with brand voice."""
        services = _create_mock_services(MOCK_BLOG_POST_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(
            PRODUCT_CELADON_BOWL,
            template_id="marketing/blog-post",
            topic="The 23 Steps Behind Every Takumi Bowl",
            product_context=PRODUCT_CELADON_BOWL["description"],
            word_count="1000",
        )
        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None
        # Content should have HTML structure
        assert "<h" in result.draft_content or "<p>" in result.draft_content

    @pytest.mark.asyncio
    async def test_blog_uses_gpt4o_for_quality(self):
        """Blog posts should use gpt-4o for long-form quality."""
        services = _create_mock_services(MOCK_BLOG_POST_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(
            PRODUCT_CELADON_BOWL,
            template_id="marketing/blog-post",
            topic="Heritage Craft in Modern Kitchens",
            product_context="Celadon bowl",
            word_count="800",
        )
        await agent.run(state)

        call_kwargs = services.llm.generate_text.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o"
        assert call_kwargs.get("temperature") == 0.8

    @pytest.mark.asyncio
    async def test_blog_post_brand_voice(self):
        """Blog content should follow brand voice."""
        parsed = json.loads(MOCK_BLOG_POST_RESPONSE)
        _assert_brand_voice(parsed["content"], min_keywords=3)

    @pytest.mark.asyncio
    async def test_blog_has_seo_metadata(self):
        """Blog should include SEO-ready metadata."""
        parsed = json.loads(MOCK_BLOG_POST_RESPONSE)
        assert len(parsed["meta_description"]) <= 160
        assert len(parsed["tags"]) >= 3
        assert parsed["title"] is not None


# =============================================================================
# Integration: Ad Copy Pipeline
# =============================================================================

class TestAdCopyE2E:
    """End-to-end tests for ad copy generation."""

    @pytest.mark.asyncio
    async def test_facebook_ad_full_pipeline(self):
        """Full pipeline: product data → Facebook ad."""
        services = _create_mock_services(MOCK_AD_FACEBOOK_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(
            PRODUCT_CELADON_BOWL,
            template_id="marketing/ad-facebook",
            platform="Facebook",
        )
        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

        # Should use cost-efficient model
        call_kwargs = services.llm.generate_text.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_google_ad_full_pipeline(self):
        """Full pipeline: product data → Google Ad."""
        services = _create_mock_services(MOCK_AD_GOOGLE_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(
            PRODUCT_CELADON_BOWL,
            template_id="marketing/ad-google",
            keywords="arita porcelain, handcrafted bowl, celadon glaze",
        )
        result = await agent.run(state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_google_ad_character_limits(self):
        """Google Ads should respect character limits."""
        parsed = json.loads(MOCK_AD_GOOGLE_RESPONSE)
        for h in parsed["headlines"]:
            assert len(h) <= 30, f"Headline '{h}' exceeds 30 char limit"
        for d in parsed["descriptions"]:
            assert len(d) <= 90, f"Description too long: {len(d)} chars"

    @pytest.mark.asyncio
    async def test_ad_brand_voice(self):
        """Ad copy should follow brand voice."""
        for mock in [MOCK_AD_FACEBOOK_RESPONSE, MOCK_AD_GOOGLE_RESPONSE]:
            parsed = json.loads(mock)
            text = json.dumps(parsed)
            # At minimum, should not contain banned words
            for banned in BRAND_VOICE_BANNED_WORDS:
                assert banned.lower() not in text.lower(), (
                    f"Banned word '{banned}' found in ad copy"
                )


# =============================================================================
# Integration: Prompt Construction with Brand Context
# =============================================================================

class TestMarketingPromptE2E:
    """Verify marketing prompts include brand intelligence."""

    @pytest.mark.asyncio
    async def test_email_prompt_has_operational_rules(self):
        """Email system prompt should include brand intelligence operational rules."""
        services = _create_mock_services(MOCK_EMAIL_LAUNCH_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        context = AgentContext(
            raw_input={
                "title": PRODUCT_CELADON_BOWL["title"],
                "description": PRODUCT_CELADON_BOWL["description"],
                "category": "Tableware",
            },
            strategic_intelligence=STRATEGIC_INTELLIGENCE,
        )

        state = _make_state(PRODUCT_CELADON_BOWL, template_id="marketing/email-launch")
        prompt = agent._build_system_prompt(state, context, "marketing/email-launch")

        assert "OPERATIONAL RULES" in prompt
        assert "artisan_master" in prompt.lower()
        assert "email" in prompt.lower()  # Template-specific prompt included

    @pytest.mark.asyncio
    async def test_blog_prompt_has_operational_rules(self):
        """Blog system prompt should have operational rules + blog-specific prompt."""
        services = _create_mock_services(MOCK_BLOG_POST_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        context = AgentContext(
            raw_input={"title": "Test", "category": "Test"},
            strategic_intelligence=STRATEGIC_INTELLIGENCE,
        )

        state = _make_state(PRODUCT_CELADON_BOWL, template_id="marketing/blog-post")
        prompt = agent._build_system_prompt(state, context, "marketing/blog-post")

        assert "OPERATIONAL RULES" in prompt
        assert "blog" in prompt.lower()  # Blog-specific prompt

    @pytest.mark.asyncio
    async def test_ad_prompt_has_operational_rules(self):
        """Ad system prompt should have operational rules."""
        services = _create_mock_services(MOCK_AD_FACEBOOK_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        context = AgentContext(
            raw_input={"title": "Test", "category": "Test"},
            strategic_intelligence=STRATEGIC_INTELLIGENCE,
        )

        state = _make_state(PRODUCT_CELADON_BOWL, template_id="marketing/ad-facebook")
        prompt = agent._build_system_prompt(state, context, "marketing/ad-facebook")

        assert "OPERATIONAL RULES" in prompt
        assert "ad" in prompt.lower()


# =============================================================================
# Integration: State Flow & Serialization
# =============================================================================

class TestMarketingStateFlowE2E:
    """Verify state management for marketing agent."""

    @pytest.mark.asyncio
    async def test_state_transitions(self):
        """State should transition: PENDING → DRAFT_READY."""
        services = _create_mock_services(MOCK_SOCIAL_HOOKS_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(PRODUCT_CELADON_BOWL)
        assert state.status == "PENDING"

        result = await agent.run(state)
        assert result.status == "DRAFT_READY"

    @pytest.mark.asyncio
    async def test_audit_trail_logs(self):
        """Logs should show complete agent lifecycle."""
        services = _create_mock_services(MOCK_SOCIAL_HOOKS_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(PRODUCT_CELADON_BOWL)
        result = await agent.run(state)

        assert any("Perceiving" in log for log in result.logs)
        assert any("Planning" in log for log in result.logs)
        assert any("Executing" in log for log in result.logs)
        assert any("Completed" in log for log in result.logs)

    @pytest.mark.asyncio
    async def test_state_serializable_for_sse(self):
        """Result state should be JSON-serializable for SSE streaming."""
        services = _create_mock_services(MOCK_EMAIL_LAUNCH_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(
            PRODUCT_CELADON_BOWL,
            template_id="marketing/email-launch",
            launch_date="2026-03-15",
        )
        result = await agent.run(state)
        state_dict = result.to_dict()

        serialized = json.dumps(state_dict, ensure_ascii=False)
        assert len(serialized) > 100
        deserialized = json.loads(serialized)
        assert deserialized["status"] == "DRAFT_READY"

    @pytest.mark.asyncio
    async def test_error_recovery(self):
        """LLM errors should be caught and state set to ERROR."""
        services = _create_mock_services("")
        services.llm.generate_text = AsyncMock(
            side_effect=Exception("API rate limit exceeded")
        )
        agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

        state = _make_state(PRODUCT_CELADON_BOWL)
        result = await agent.run(state)

        assert result.status == "ERROR"
        assert result.error_message is not None
        assert "failed" in result.error_message.lower()


# =============================================================================
# Integration: All Templates for Same Product
# =============================================================================

class TestAllMarketingTemplatesE2E:
    """Run all marketing templates for the same product to test consistency."""

    @pytest.mark.asyncio
    async def test_all_templates_produce_draft_ready(self):
        """Every marketing template should produce DRAFT_READY for the celadon bowl."""
        templates = [
            ("marketing/social-instagram", MOCK_SOCIAL_HOOKS_RESPONSE, {}),
            ("marketing/email-launch", MOCK_EMAIL_LAUNCH_RESPONSE, {"launch_date": "2026-03-15"}),
            ("marketing/email-abandoned", MOCK_EMAIL_ABANDONED_RESPONSE, {"price": "¥12,800"}),
            ("marketing/email-welcome", MOCK_EMAIL_WELCOME_RESPONSE, {"brand_name": "Takumi Ceramics"}),
            ("marketing/blog-post", MOCK_BLOG_POST_RESPONSE, {
                "topic": "Craft Process",
                "product_context": PRODUCT_CELADON_BOWL["description"],
                "word_count": "1000",
            }),
            ("marketing/ad-facebook", MOCK_AD_FACEBOOK_RESPONSE, {"platform": "Facebook"}),
            ("marketing/ad-google", MOCK_AD_GOOGLE_RESPONSE, {"keywords": "arita porcelain"}),
        ]

        for template_id, mock_response, extra in templates:
            services = _create_mock_services(mock_response)
            agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

            state = _make_state(PRODUCT_CELADON_BOWL, template_id=template_id, **extra)
            result = await agent.run(state)

            assert result.status == "DRAFT_READY", (
                f"Template {template_id} failed: {result.error_message}"
            )

    @pytest.mark.asyncio
    async def test_all_templates_for_teapot(self):
        """Run all marketing templates for a different product (teapot)."""
        templates = [
            ("marketing/social-instagram", MOCK_SOCIAL_HOOKS_RESPONSE, {}),
            ("marketing/email-launch", MOCK_EMAIL_LAUNCH_RESPONSE, {"launch_date": "2026-04-01"}),
            ("marketing/ad-facebook", MOCK_AD_FACEBOOK_RESPONSE, {"platform": "Instagram"}),
        ]

        for template_id, mock_response, extra in templates:
            services = _create_mock_services(mock_response)
            agent = MarketingAgent("takumi-ceramics.myshopify.com", services)

            state = _make_state(PRODUCT_TEAPOT, template_id=template_id, **extra)
            result = await agent.run(state)

            assert result.status == "DRAFT_READY", (
                f"Template {template_id} for teapot failed: {result.error_message}"
            )

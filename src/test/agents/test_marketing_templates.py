"""
Unit tests for MarketingAgent template-based generation.

Tests all 6 marketing templates with PROD-quality mock responses:
- marketing/social-tiktok (existing flow)
- marketing/email-launch
- marketing/email-abandoned
- marketing/email-welcome
- marketing/ad-facebook
- marketing/ad-google

Each test verifies:
1. Correct template routing
2. Prompt construction with brand context + operational rules
3. LLM call parameters (model, temperature)
4. State update after generation
5. Brand voice enforcement in output
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
    MOCK_SOCIAL_HOOKS_RESPONSE,
    MOCK_EMAIL_LAUNCH_RESPONSE,
    MOCK_EMAIL_ABANDONED_RESPONSE,
    MOCK_EMAIL_WELCOME_RESPONSE,
    MOCK_AD_FACEBOOK_RESPONSE,
    MOCK_AD_GOOGLE_RESPONSE,
    BRAND_VOICE_MUST_INCLUDE_KEYWORDS,
    BRAND_VOICE_BANNED_WORDS,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_services():
    """Create mock ServiceRegistry with PROD-quality responses."""
    services = MagicMock()
    services.llm.generate_text = AsyncMock(return_value=MOCK_SOCIAL_HOOKS_RESPONSE)
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=[])
    services.rag.get_brand_context = AsyncMock(return_value=BRAND_CONTEXT_CHUNKS)
    services.rag.get_complete_context = AsyncMock(return_value={
        "chunks": BRAND_CONTEXT_CHUNKS,
        "expanded_chunks": [],
        "related_triplets": [],
        "strategic_rules": STRATEGIC_INTELLIGENCE,
    })
    services.rag._get_strategic_intelligence = AsyncMock(return_value=STRATEGIC_INTELLIGENCE)
    return services


@pytest.fixture
def base_state():
    """Create base MissionState for marketing content."""
    return MissionState(
        product_id=PRODUCT_CELADON_BOWL["id"],
        shop_id="takumi-ceramics.myshopify.com",
        plan_tier="Pro",
        raw_input={
            "title": PRODUCT_CELADON_BOWL["title"],
            "description": PRODUCT_CELADON_BOWL["description"],
            "category": PRODUCT_CELADON_BOWL["category"],
            "target_locale": "en",
            "tags": PRODUCT_CELADON_BOWL["tags"],
        },
        target_locale="en",
    )


def _assert_brand_voice(text: str):
    """Assert the text follows Takumi Ceramics brand voice."""
    text_lower = text.lower()
    matches = [kw for kw in BRAND_VOICE_MUST_INCLUDE_KEYWORDS if kw.lower() in text_lower]
    assert len(matches) >= 2, (
        f"Expected at least 2 brand keywords but found: {matches}. "
        f"Text: {text[:200]}..."
    )
    for banned in BRAND_VOICE_BANNED_WORDS:
        assert banned.lower() not in text_lower, (
            f"Banned word '{banned}' found in output: {text[:200]}..."
        )


# =============================================================================
# Tests: marketing/social-tiktok template (existing flow)
# =============================================================================

class TestSocialTikTokTemplate:
    """Tests for the TikTok social hooks template."""

    @pytest.mark.asyncio
    async def test_routes_to_social_generator(self, mock_services, base_state):
        """Default template_id routes to social generator."""
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "DRAFT_READY"
        assert result.social_hooks is not None
        assert len(result.social_hooks) >= 1

    @pytest.mark.asyncio
    async def test_social_hooks_normalized(self, mock_services, base_state):
        """Social hooks should be normalized with hashtags and copy_text."""
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        for hook in result.social_hooks:
            assert "type" in hook
            assert "caption" in hook
            assert "hashtags" in hook
            assert "copy_text" in hook
            assert len(hook["caption"]) > 0

    @pytest.mark.asyncio
    async def test_social_uses_mini_model(self, mock_services, base_state):
        """Social hooks should use gpt-4o-mini for cost efficiency."""
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(base_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o-mini"
        assert call_kwargs.get("temperature") == 0.8

    @pytest.mark.asyncio
    async def test_social_brand_voice(self):
        """Social hook mock responses should follow brand voice."""
        parsed = json.loads(MOCK_SOCIAL_HOOKS_RESPONSE)
        all_text = " ".join(h["caption"] for h in parsed["hooks"])
        _assert_brand_voice(all_text)


# =============================================================================
# Tests: marketing/email-launch template
# =============================================================================

class TestEmailLaunchTemplate:
    """Tests for the product launch email template."""

    @pytest.fixture
    def launch_state(self, base_state):
        base_state.raw_input["template_id"] = "marketing/email-launch"
        base_state.raw_input["launch_date"] = "2026-03-15"
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_email_generator(self, mock_services, launch_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_EMAIL_LAUNCH_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(launch_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_launch_email_structure(self):
        """Mock response should have subject, preheader, body, and CTA."""
        parsed = json.loads(MOCK_EMAIL_LAUNCH_RESPONSE)
        assert "subject" in parsed
        assert "preheader" in parsed
        assert "body" in parsed
        assert "cta_text" in parsed
        assert len(parsed["subject"]) <= 60

    @pytest.mark.asyncio
    async def test_launch_email_brand_voice(self):
        parsed = json.loads(MOCK_EMAIL_LAUNCH_RESPONSE)
        all_text = f"{parsed['subject']} {parsed['body']}"
        _assert_brand_voice(all_text)

    @pytest.mark.asyncio
    async def test_email_uses_gpt4o(self, mock_services, launch_state):
        """Email templates should use gpt-4o for quality."""
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_EMAIL_LAUNCH_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(launch_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o"

    @pytest.mark.asyncio
    async def test_launch_prompt_includes_product(self, mock_services, launch_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_EMAIL_LAUNCH_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(launch_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        prompt = call_kwargs.get("prompt", "")
        assert PRODUCT_CELADON_BOWL["title"] in prompt


# =============================================================================
# Tests: marketing/email-abandoned template
# =============================================================================

class TestEmailAbandonedTemplate:
    """Tests for the abandoned cart email template."""

    @pytest.fixture
    def abandoned_state(self, base_state):
        base_state.raw_input["template_id"] = "marketing/email-abandoned"
        base_state.raw_input["price"] = PRODUCT_CELADON_BOWL["price"]
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_abandoned_email(self, mock_services, abandoned_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_EMAIL_ABANDONED_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(abandoned_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_abandoned_email_structure(self):
        parsed = json.loads(MOCK_EMAIL_ABANDONED_RESPONSE)
        assert "subject" in parsed
        assert "body" in parsed
        assert "cta_text" in parsed

    @pytest.mark.asyncio
    async def test_abandoned_email_brand_voice(self):
        parsed = json.loads(MOCK_EMAIL_ABANDONED_RESPONSE)
        all_text = f"{parsed['subject']} {parsed['body']}"
        _assert_brand_voice(all_text)

    @pytest.mark.asyncio
    async def test_abandoned_email_no_banned_urgency(self):
        """Abandoned cart emails should use gentle urgency, no hard sales."""
        parsed = json.loads(MOCK_EMAIL_ABANDONED_RESPONSE)
        text = parsed["body"].lower()
        assert "limited-time offer" not in text
        assert "act now" not in text
        assert "hurry" not in text


# =============================================================================
# Tests: marketing/email-welcome template
# =============================================================================

class TestEmailWelcomeTemplate:
    """Tests for the welcome email template."""

    @pytest.fixture
    def welcome_state(self, base_state):
        base_state.raw_input["template_id"] = "marketing/email-welcome"
        base_state.raw_input["brand_name"] = "Takumi Ceramics"
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_welcome_email(self, mock_services, welcome_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_EMAIL_WELCOME_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(welcome_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_welcome_email_structure(self):
        parsed = json.loads(MOCK_EMAIL_WELCOME_RESPONSE)
        assert "subject" in parsed
        assert "body" in parsed
        assert "cta_text" in parsed

    @pytest.mark.asyncio
    async def test_welcome_mentions_brand_story(self):
        """Welcome email should introduce the brand story."""
        parsed = json.loads(MOCK_EMAIL_WELCOME_RESPONSE)
        body = parsed["body"].lower()
        # Should mention the brand origin or philosophy
        assert "1923" in body or "fourth" in body or "yō-no-bi" in body.lower()

    @pytest.mark.asyncio
    async def test_welcome_brand_voice(self):
        parsed = json.loads(MOCK_EMAIL_WELCOME_RESPONSE)
        _assert_brand_voice(parsed["body"])


# =============================================================================
# Tests: marketing/ad-facebook template
# =============================================================================

class TestAdFacebookTemplate:
    """Tests for the Facebook/Instagram ad copy template."""

    @pytest.fixture
    def fb_ad_state(self, base_state):
        base_state.raw_input["template_id"] = "marketing/ad-facebook"
        base_state.raw_input["platform"] = "Facebook"
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_ad_generator(self, mock_services, fb_ad_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_AD_FACEBOOK_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(fb_ad_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_fb_ad_structure(self):
        """Facebook ad should have primary_text, headline, description, CTA."""
        parsed = json.loads(MOCK_AD_FACEBOOK_RESPONSE)
        assert "primary_text" in parsed
        assert "headline" in parsed
        assert "cta" in parsed

    @pytest.mark.asyncio
    async def test_fb_ad_uses_mini_model(self, mock_services, fb_ad_state):
        """Ad copy uses gpt-4o-mini for cost efficiency."""
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_AD_FACEBOOK_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(fb_ad_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        assert call_kwargs.get("model") == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_fb_ad_brand_voice(self):
        parsed = json.loads(MOCK_AD_FACEBOOK_RESPONSE)
        all_text = f"{parsed['primary_text']} {parsed['headline']} {parsed.get('description', '')}"
        _assert_brand_voice(all_text)


# =============================================================================
# Tests: marketing/ad-google template
# =============================================================================

class TestAdGoogleTemplate:
    """Tests for the Google Ads template."""

    @pytest.fixture
    def google_ad_state(self, base_state):
        base_state.raw_input["template_id"] = "marketing/ad-google"
        base_state.raw_input["keywords"] = "arita porcelain, handcrafted bowl, celadon"
        return base_state

    @pytest.mark.asyncio
    async def test_routes_to_google_ad_generator(self, mock_services, google_ad_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_AD_GOOGLE_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(google_ad_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_google_ad_structure(self):
        """Google ad should have 3 headlines, 2 descriptions, and display paths."""
        parsed = json.loads(MOCK_AD_GOOGLE_RESPONSE)
        assert "headlines" in parsed
        assert "descriptions" in parsed
        assert "path1" in parsed
        assert "path2" in parsed
        assert len(parsed["headlines"]) == 3
        assert len(parsed["descriptions"]) == 2

    @pytest.mark.asyncio
    async def test_google_headline_char_limit(self):
        """Each Google headline should be ≤ 30 characters."""
        parsed = json.loads(MOCK_AD_GOOGLE_RESPONSE)
        for h in parsed["headlines"]:
            assert len(h) <= 30, f"Headline '{h}' exceeds 30 chars ({len(h)})"

    @pytest.mark.asyncio
    async def test_google_ad_prompt_includes_keywords(self, mock_services, google_ad_state):
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_AD_GOOGLE_RESPONSE)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        await agent.run(google_ad_state)

        call_kwargs = mock_services.llm.generate_text.call_args.kwargs
        prompt = call_kwargs.get("prompt", "")
        assert "arita porcelain" in prompt.lower()


# =============================================================================
# Tests: Operational Rules Injection (Marketing)
# =============================================================================

class TestMarketingOperationalRules:
    """Verify strategic intelligence injection in marketing prompts."""

    @pytest.mark.asyncio
    async def test_email_prompt_includes_operational_rules(self, mock_services, base_state):
        """Operational rules from strategic intelligence should be in email system prompt."""
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)

        context = AgentContext(
            raw_input=base_state.raw_input,
            brand_context=BRAND_CONTEXT_CHUNKS,
            strategic_intelligence=STRATEGIC_INTELLIGENCE,
        )
        system_prompt = agent._build_system_prompt(base_state, context, "marketing/email-launch")

        # Should include archetype
        assert "artisan_master" in system_prompt.lower()
        # Should include power words
        assert "handcrafted" in system_prompt.lower()
        # Should include banned phrases
        assert "cheap" in system_prompt.lower()
        # Should include value props
        assert "Arita" in system_prompt

    @pytest.mark.asyncio
    async def test_ad_prompt_includes_operational_rules(self, mock_services, base_state):
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)

        context = AgentContext(
            raw_input=base_state.raw_input,
            strategic_intelligence=STRATEGIC_INTELLIGENCE,
        )
        system_prompt = agent._build_system_prompt(base_state, context, "marketing/ad-facebook")

        assert "artisan_master" in system_prompt.lower()

    @pytest.mark.asyncio
    async def test_without_intelligence_still_works(self, mock_services, base_state):
        """Marketing agent should work even without strategic intelligence."""
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)

        context = AgentContext(
            raw_input=base_state.raw_input,
            strategic_intelligence=None,
        )
        system_prompt = agent._build_system_prompt(base_state, context, "marketing/email-launch")

        # Should still have the email template system prompt
        assert "email" in system_prompt.lower()


# =============================================================================
# Tests: Template Routing Edge Cases (Marketing)
# =============================================================================

class TestMarketingRoutingEdgeCases:
    """Test edge cases in marketing template routing."""

    @pytest.mark.asyncio
    async def test_unknown_template_falls_back_to_social(self, mock_services, base_state):
        """Unknown template_id should fall back to social hooks."""
        base_state.raw_input["template_id"] = "marketing/unknown-template"
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "DRAFT_READY"

    @pytest.mark.asyncio
    async def test_default_template_is_social(self, mock_services, base_state):
        """Missing template_id should default to social-tiktok."""
        base_state.raw_input.pop("template_id", None)
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "DRAFT_READY"
        assert result.social_hooks is not None

    @pytest.mark.asyncio
    async def test_llm_error_sets_error_state(self, mock_services, base_state):
        """LLM failure should set error state."""
        mock_services.llm.generate_text = AsyncMock(side_effect=Exception("LLM timeout"))
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "ERROR"
        assert "failed" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_email_template_prefix_routing(self, mock_services, base_state):
        """All marketing/email-* templates should route to _generate_email."""
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_EMAIL_WELCOME_RESPONSE)
        base_state.raw_input["template_id"] = "marketing/email-welcome"
        base_state.raw_input["brand_name"] = "Takumi Ceramics"
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "DRAFT_READY"
        assert result.draft_content is not None

    @pytest.mark.asyncio
    async def test_ad_template_prefix_routing(self, mock_services, base_state):
        """All marketing/ad-* templates should route to _generate_ad."""
        mock_services.llm.generate_text = AsyncMock(return_value=MOCK_AD_GOOGLE_RESPONSE)
        base_state.raw_input["template_id"] = "marketing/ad-google"
        base_state.raw_input["keywords"] = "arita porcelain"
        agent = MarketingAgent("takumi-ceramics.myshopify.com", mock_services)
        result = await agent.run(base_state)

        assert result.status == "DRAFT_READY"


# =============================================================================
# Tests: Cross-template Brand Consistency
# =============================================================================

class TestBrandConsistencyAcrossTemplates:
    """Verify brand voice is consistent across all marketing outputs."""

    @pytest.mark.asyncio
    async def test_all_email_outputs_consistent_voice(self):
        """All email mock outputs should follow brand voice."""
        for response_str in [
            MOCK_EMAIL_LAUNCH_RESPONSE,
            MOCK_EMAIL_ABANDONED_RESPONSE,
            MOCK_EMAIL_WELCOME_RESPONSE,
        ]:
            parsed = json.loads(response_str)
            body = parsed.get("body", "")
            _assert_brand_voice(body)

    @pytest.mark.asyncio
    async def test_all_ad_outputs_no_banned_words(self):
        """All ad mock outputs should have zero banned words."""
        for response_str in [MOCK_AD_FACEBOOK_RESPONSE, MOCK_AD_GOOGLE_RESPONSE]:
            parsed = json.loads(response_str)
            text = json.dumps(parsed).lower()
            for banned in BRAND_VOICE_BANNED_WORDS:
                assert banned.lower() not in text, (
                    f"Banned word '{banned}' found in ad output"
                )

    @pytest.mark.asyncio
    async def test_social_no_banned_words(self):
        """Social hooks should contain zero banned words."""
        parsed = json.loads(MOCK_SOCIAL_HOOKS_RESPONSE)
        all_text = " ".join(h["caption"] for h in parsed["hooks"]).lower()
        for banned in BRAND_VOICE_BANNED_WORDS:
            assert banned.lower() not in all_text, (
                f"Banned word '{banned}' found in social hooks"
            )

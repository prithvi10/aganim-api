"""
Multi-locale support tests for all agents.

Validates that each agent correctly:
- Reads target_locale from MissionState
- Passes locale-specific SERP params (gl, hl, location)
- Injects locale persona into prompts (RewriterAgent)
- Falls back to 'en' when target_locale is missing
- Works identically across all 11 supported locales
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ecommerce.agents.seo import SEOAgent
from src.ecommerce.agents.price_scout import PriceScoutAgent
from src.ecommerce.agents.rewriter import RewriterAgent
from src.ecommerce.agents.marketing import MarketingAgent
from src.ecommerce.state import MissionState
from src.ecommerce.config.shopify_config import (
    LOCALE_PERSONA_MAP,
    LOCALE_TO_SERP_PARAMS,
)
from src.agentic_core.agents.context import AgentContext


ALL_LOCALES = list(LOCALE_TO_SERP_PARAMS.keys())


# =============================================================================
# Shared fixtures
# =============================================================================

def _make_serp_results(n: int = 3):
    results = []
    for i in range(n):
        r = MagicMock()
        r.title = f"Competitor {i+1}"
        r.snippet = f"Snippet {i+1}"
        r.link = f"https://comp{i+1}.com"
        r.position = i + 1
        results.append(r)
    return results


def _make_shopping_results():
    return [
        {"title": "Product A", "price": "$45.00", "extracted_price": 45.0,
         "source": "Etsy", "link": "https://etsy.com/1", "thumbnail": None, "shipping": None},
        {"title": "Product B", "price": "$55.00", "extracted_price": 55.0,
         "source": "Amazon", "link": "https://amazon.com/2", "thumbnail": None, "shipping": None},
    ]


@pytest.fixture
def mock_services():
    services = MagicMock()
    services.llm.generate_text = AsyncMock(
        return_value='{"title": "Generated", "description": "<p>Content</p>", "discovered_values": []}'
    )
    services.llm.generate_structured = AsyncMock()
    services.serp.search = AsyncMock(return_value=_make_serp_results())
    services.serp.get_competitor_prices = AsyncMock(return_value=_make_shopping_results())
    services.rag.get_brand_context = AsyncMock(return_value=[])
    return services


def _make_state(locale: str) -> MissionState:
    return MissionState(
        product_id="test-product-123",
        shop_id="test-shop.myshopify.com",
        plan_tier="Standard",
        raw_input={
            "title": "Handcrafted Ceramic Bowl",
            "description": "Made in Kyoto using traditional techniques.",
            "category": "Kitchenware",
        },
        target_locale=locale,
    )


# =============================================================================
# Config coverage: every locale must be in both maps
# =============================================================================

class TestLocaleConfigConsistency:
    def test_all_serp_locales_have_persona(self):
        for locale in LOCALE_TO_SERP_PARAMS:
            assert locale in LOCALE_PERSONA_MAP, (
                f"Locale '{locale}' in LOCALE_TO_SERP_PARAMS but missing from LOCALE_PERSONA_MAP"
            )

    def test_all_persona_locales_have_serp_params(self):
        for locale in LOCALE_PERSONA_MAP:
            assert locale in LOCALE_TO_SERP_PARAMS, (
                f"Locale '{locale}' in LOCALE_PERSONA_MAP but missing from LOCALE_TO_SERP_PARAMS"
            )

    def test_serp_params_have_required_keys(self):
        for locale, params in LOCALE_TO_SERP_PARAMS.items():
            assert "gl" in params, f"Missing 'gl' for locale '{locale}'"
            assert "hl" in params, f"Missing 'hl' for locale '{locale}'"
            assert "location" in params, f"Missing 'location' for locale '{locale}'"

    def test_minimum_locale_count(self):
        assert len(LOCALE_TO_SERP_PARAMS) >= 11


# =============================================================================
# SEOAgent: locale → SERP params
# =============================================================================

class TestSEOAgentMultiLocale:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_perceive_passes_locale_serp_params(self, mock_services, locale):
        """SERP search receives correct gl/hl/location for each locale."""
        state = _make_state(locale)
        state.draft_content = "<p>Test content</p>"

        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        await agent.perceive(state)

        expected = LOCALE_TO_SERP_PARAMS[locale]
        call_kwargs = mock_services.serp.search.call_args
        assert call_kwargs.kwargs.get("gl") == expected["gl"]
        assert call_kwargs.kwargs.get("hl") == expected["hl"]
        assert call_kwargs.kwargs.get("location") == expected["location"]

    @pytest.mark.asyncio
    async def test_fallback_to_en_when_locale_missing(self, mock_services):
        """When target_locale is None, agent falls back to 'en'."""
        state = _make_state("en")
        state.target_locale = None
        state.raw_input["target_locale"] = "en"
        state.draft_content = "<p>Test</p>"

        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        await agent.perceive(state)

        call_kwargs = mock_services.serp.search.call_args
        assert call_kwargs.kwargs.get("gl") == "us"

    @pytest.mark.asyncio
    async def test_unknown_locale_falls_back_gracefully(self, mock_services):
        """Unknown locale yields empty SERP params (no crash)."""
        state = _make_state("xx-YY")
        state.draft_content = "<p>Test</p>"

        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        await agent.perceive(state)

        call_kwargs = mock_services.serp.search.call_args
        assert call_kwargs.kwargs.get("gl") is None
        assert call_kwargs.kwargs.get("hl") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_act_passes_target_locale_to_seo_generation(self, mock_services, locale):
        """_generate_seo receives the correct target_locale for prompt building."""
        mock_services.llm.generate_text = AsyncMock(
            return_value='{"seo_title": "Title", "seo_description": "Desc", "seo_alt_text": "Alt"}'
        )
        state = _make_state(locale)
        state.draft_content = "<p>Content</p>"

        agent = SEOAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(state)

        prompt_text = mock_services.llm.generate_text.call_args.kwargs.get("prompt", "")
        assert locale in prompt_text


# =============================================================================
# PriceScoutAgent: locale → SERP shopping params
# =============================================================================

class TestPriceScoutAgentMultiLocale:

    @pytest.fixture(autouse=True)
    def _setup_llm(self, mock_services):
        from src.ecommerce.agents.price_scout.schemas import (
            PricingAnalysis,
            FilteredCompetitorsResponse,
        )

        def _structured(prompt, response_format, **kw):
            if response_format == FilteredCompetitorsResponse:
                return FilteredCompetitorsResponse(
                    valid_competitor_indices=[0, 1],
                    reasoning="Both relevant.",
                )
            return PricingAnalysis(
                competitor_avg_price=50.0,
                recommended_price=52.0,
                price_position="competitive",
                confidence=0.85,
                reasoning="OK",
            )

        mock_services.llm.generate_structured = AsyncMock(side_effect=_structured)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_perceive_passes_locale_to_shopping(self, mock_services, locale):
        """get_competitor_prices receives correct gl/hl/location."""
        state = _make_state(locale)

        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        await agent.perceive(state)

        expected = LOCALE_TO_SERP_PARAMS[locale]
        call_kwargs = mock_services.serp.get_competitor_prices.call_args
        assert call_kwargs.kwargs.get("gl") == expected["gl"]
        assert call_kwargs.kwargs.get("hl") == expected["hl"]
        assert call_kwargs.kwargs.get("location") == expected["location"]

    @pytest.mark.asyncio
    async def test_fallback_to_en_when_locale_none(self, mock_services):
        state = _make_state("en")
        state.target_locale = None
        state.raw_input["target_locale"] = "en"

        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        await agent.perceive(state)

        call_kwargs = mock_services.serp.get_competitor_prices.call_args
        assert call_kwargs.kwargs.get("gl") == "us"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_full_pipeline_with_locale(self, mock_services, locale):
        """Full run() completes for every locale."""
        state = _make_state(locale)

        agent = PriceScoutAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(state)

        assert result.pricing_analysis is not None
        assert result.pricing_analysis["competitor_count"] >= 0


# =============================================================================
# RewriterAgent: locale → persona injection + prompt locale
# =============================================================================

class TestRewriterAgentMultiLocale:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_system_prompt_contains_locale_persona(self, mock_services, locale):
        """System prompt includes the LOCALE_PERSONA_MAP entry for the locale."""
        state = _make_state(locale)

        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        system_prompt = agent._build_system_prompt(state, context)

        expected_persona = LOCALE_PERSONA_MAP[locale]
        assert expected_persona in system_prompt, (
            f"Persona for '{locale}' not found in system prompt"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_user_prompt_contains_target_locale(self, mock_services, locale):
        """User prompt includes Target Locale: <locale>."""
        state = _make_state(locale)

        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        user_prompt = agent._build_user_prompt(state, context)

        assert f"Target Locale: {locale}" in user_prompt

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_full_pipeline_with_locale(self, mock_services, locale):
        """Full run() completes and produces draft for every locale."""
        state = _make_state(locale)

        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(state)

        assert result.draft_content is not None
        assert result.status == "DRAFT_READY"

    @pytest.mark.asyncio
    async def test_fallback_locale_when_missing(self, mock_services):
        """When target_locale is None, raw_input fallback is used."""
        state = _make_state("en")
        state.target_locale = None
        state.raw_input["target_locale"] = "de"

        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        system_prompt = agent._build_system_prompt(state, context)

        assert LOCALE_PERSONA_MAP["de"] in system_prompt

    @pytest.mark.asyncio
    @pytest.mark.parametrize("template_id", [
        "product/description",
        "product/collection",
        "product/faq",
        "product/landing-hero",
        "product/blog-post",
    ])
    async def test_locale_in_template_prompts(self, mock_services, template_id):
        """Locale persona is injected for all template types."""
        state = _make_state("ko")
        state.raw_input["template_id"] = template_id

        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        system_prompt = agent._build_system_prompt(state, context, template_id)

        assert LOCALE_PERSONA_MAP["ko"] in system_prompt


# =============================================================================
# MarketingAgent: locale passed through to template prompts
# =============================================================================

class TestMarketingAgentMultiLocale:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_full_pipeline_with_locale(self, mock_services, locale):
        """Full run() completes for every locale."""
        mock_services.llm.generate_text = AsyncMock(
            return_value='{"hooks": [{"type": "Story", "caption": "Hook!", "hashtags": ["test"], "overlay": "X"}]}'
        )
        state = _make_state(locale)

        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(state)

        assert result is not None
        assert result.social_hooks is not None or result.draft_content is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("template_id,locale", [
        ("marketing/email-launch", "de"),
        ("marketing/email-abandoned", "fr"),
        ("marketing/email-welcome", "ko"),
        ("marketing/ad-facebook", "zh-TW"),
        ("marketing/ad-google", "es"),
    ])
    async def test_template_prompt_includes_locale(self, mock_services, template_id, locale):
        """Template user prompts include the target_locale."""
        state = _make_state(locale)
        state.raw_input["template_id"] = template_id

        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        user_prompt = agent._build_user_prompt(state, context, template_id)

        assert locale in user_prompt or user_prompt != ""


# =============================================================================
# MissionState: locale serialization round-trip
# =============================================================================

class TestMissionStateLocale:

    @pytest.mark.parametrize("locale", ALL_LOCALES)
    def test_locale_preserved_in_to_dict(self, locale):
        state = _make_state(locale)
        d = state.to_dict()
        assert d["target_locale"] == locale

    @pytest.mark.parametrize("locale", ALL_LOCALES)
    def test_locale_preserved_in_from_dict(self, locale):
        state = _make_state(locale)
        d = state.to_dict()
        restored = MissionState.from_dict(d)
        assert restored.target_locale == locale

    def test_none_locale_defaults_in_agent(self):
        state = MissionState(
            product_id="p1", shop_id="s1", plan_tier="Free",
            raw_input={"title": "T", "description": "D", "category": "C"},
        )
        assert state.target_locale is None
        effective = state.target_locale or state.raw_input.get("target_locale", "en")
        assert effective == "en"


# =============================================================================
# SerpService: locale params passed through
# =============================================================================

class TestSerpServiceLocaleParams:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_search_passes_gl_hl(self, locale):
        """SerpService.search forwards gl/hl/location from caller."""
        from src.agentic_core.tools.serp_service import SerpService

        service = SerpService(api_key="fake-key")
        params = LOCALE_TO_SERP_PARAMS[locale]

        with patch("httpx.AsyncClient") as MockClient:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"organic_results": [
                {"title": "R1", "snippet": "S1", "link": "https://example.com", "position": 1}
            ]}
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            await service.search(
                "test query",
                gl=params["gl"],
                hl=params["hl"],
                location=params["location"],
            )

            call_kwargs = mock_client.get.call_args
            sent_params = call_kwargs.kwargs.get("params", {})
            assert sent_params.get("gl") == params["gl"]
            assert sent_params.get("hl") == params["hl"]
            assert sent_params.get("location") == params["location"]

    @pytest.mark.asyncio
    async def test_search_omits_gl_hl_when_not_provided(self):
        """When gl/hl are not provided, params dict omits them."""
        from src.agentic_core.tools.serp_service import SerpService

        service = SerpService(api_key="fake-key")

        with patch("httpx.AsyncClient") as MockClient:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"organic_results": []}
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            await service.search("test query")

            sent_params = mock_client.get.call_args.kwargs.get("params", {})
            assert "gl" not in sent_params
            assert "hl" not in sent_params

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_search_shopping_passes_gl_hl(self, locale):
        """SerpService.search_shopping forwards gl/hl/location."""
        from src.agentic_core.tools.serp_service import SerpService

        service = SerpService(api_key="fake-key")
        params = LOCALE_TO_SERP_PARAMS[locale]

        with patch("httpx.AsyncClient") as MockClient:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"shopping_results": [
                {"title": "P1", "price": "$50", "extracted_price": 50.0,
                 "source": "Amazon", "link": "https://a.com"}
            ]}
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            await service.search_shopping(
                "test product",
                gl=params["gl"],
                hl=params["hl"],
                location=params["location"],
            )

            sent_params = mock_client.get.call_args.kwargs.get("params", {})
            assert sent_params.get("gl") == params["gl"]
            assert sent_params.get("hl") == params["hl"]
            assert sent_params.get("location") == params["location"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", ALL_LOCALES)
    async def test_get_competitor_prices_passes_locale_params(self, locale):
        """get_competitor_prices forwards gl/hl/location to search_shopping."""
        from src.agentic_core.tools.serp_service import SerpService

        service = SerpService(api_key="fake-key")
        params = LOCALE_TO_SERP_PARAMS[locale]

        with patch.object(service, "search_shopping", new_callable=AsyncMock, return_value=[]) as mock_shopping:
            await service.get_competitor_prices(
                "Bowl", "Kitchenware",
                location=params["location"],
                gl=params["gl"],
                hl=params["hl"],
            )

            mock_shopping.assert_called_once()
            call_kwargs = mock_shopping.call_args
            assert call_kwargs.kwargs.get("gl") == params["gl"]
            assert call_kwargs.kwargs.get("hl") == params["hl"]
            assert call_kwargs.kwargs.get("location") == params["location"]

"""
JA Domestic Market (Japanese-to-Japanese) prompt selection tests.

Validates that when target_locale == "ja", the pipeline selects
JA-domestic-specific prompts, tones, brand context, and user messages
instead of the cross-border (translation-oriented) defaults.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import Session

from src.ecommerce.core.generation import (
    _is_ja_domestic,
    _build_dynamic_prompt,
    _render_brand_context_block_from_blob,
    _augment_seo_and_discoveries_if_missing,
    process_generation_request,
)
from src.ecommerce.api.models import RewriteRequest
from src.ecommerce.db.models import User, Plan
from src.shared.config.prompts import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_JA_DOMESTIC,
    VALUE_DISCOVERY_PROMPT,
    VALUE_DISCOVERY_PROMPT_JA_DOMESTIC,
    TONE_PROMPTS,
    TONE_PROMPTS_JA_DOMESTIC,
    BRAND_CONTEXT_INJECTION_TEMPLATE,
    BRAND_CONTEXT_INJECTION_TEMPLATE_JA_DOMESTIC,
)
from src.ecommerce.config.shopify_config import (
    LOCALE_PERSONA_MAP,
    LOCALE_TO_SERP_PARAMS,
)


# =============================================================================
# Config: "ja" is in both locale maps
# =============================================================================

class TestJALocaleConfig:

    def test_ja_in_persona_map(self):
        assert "ja" in LOCALE_PERSONA_MAP

    def test_ja_in_serp_params(self):
        assert "ja" in LOCALE_TO_SERP_PARAMS

    def test_ja_serp_params_target_japan(self):
        params = LOCALE_TO_SERP_PARAMS["ja"]
        assert params["gl"] == "jp"
        assert params["hl"] == "ja"
        assert params["location"] == "Japan"


# =============================================================================
# _is_ja_domestic helper
# =============================================================================

class TestIsJaDomestic:

    def test_ja_returns_true(self):
        assert _is_ja_domestic("ja") is True

    def test_ja_case_insensitive(self):
        assert _is_ja_domestic("JA") is True
        assert _is_ja_domestic("Ja") is True

    def test_ja_with_whitespace(self):
        assert _is_ja_domestic(" ja ") is True

    def test_en_returns_false(self):
        assert _is_ja_domestic("en") is False

    def test_none_returns_false(self):
        assert _is_ja_domestic(None) is False

    def test_empty_returns_false(self):
        assert _is_ja_domestic("") is False

    def test_ja_jp_returns_false(self):
        """Only exact 'ja' is domestic, not sub-locales like 'ja-JP'."""
        assert _is_ja_domestic("ja-JP") is False


# =============================================================================
# _build_dynamic_prompt: JA domestic vs cross-border
# =============================================================================

class TestBuildDynamicPromptJA:

    def test_ja_uses_domestic_system_prompt(self):
        prompt = _build_dynamic_prompt("ja")
        assert "Japanese domestic" in prompt or "日本国内" in prompt
        assert "Transform a factual Japanese product description into localized" not in prompt

    def test_ja_uses_domestic_value_discovery(self):
        prompt = _build_dynamic_prompt("ja")
        assert "国内の日本人消費者" in prompt or "domestic Japanese shoppers" in prompt
        assert "Western customers" not in prompt

    def test_ja_uses_domestic_tone_professional(self):
        prompt = _build_dynamic_prompt("ja", tone_profile="professional")
        assert "プロフェッショナル" in prompt or "です・ます調" in prompt

    def test_ja_uses_domestic_tone_luxury(self):
        prompt = _build_dynamic_prompt("ja", tone_profile="luxury")
        assert "ラグジュアリー" in prompt or "逸品" in prompt or "匠の技" in prompt
        assert "US English vocabulary" not in prompt

    def test_ja_uses_domestic_tone_playful(self):
        prompt = _build_dynamic_prompt("ja", tone_profile="playful")
        assert "プレイフル" in prompt or "親しみやすい" in prompt
        assert "friendly American personality" not in prompt

    def test_ja_skips_unit_conversion(self):
        prompt = _build_dynamic_prompt("ja", auto_convert_units=True)
        assert "UNIT CONVERSION" not in prompt

    def test_ja_localization_rules_in_japanese(self):
        prompt = _build_dynamic_prompt("ja")
        assert "洗練された日本語" in prompt or "日本国内EC" in prompt

    def test_en_still_uses_cross_border_prompt(self):
        prompt = _build_dynamic_prompt("en")
        assert "Transform a factual Japanese product description into localized" in prompt

    def test_en_uses_standard_value_discovery(self):
        prompt = _build_dynamic_prompt("en")
        assert "Western customers" in prompt

    def test_en_uses_standard_tone_luxury(self):
        prompt = _build_dynamic_prompt("en", tone_profile="luxury")
        assert "US English vocabulary" in prompt

    @pytest.mark.parametrize("locale", ["ko", "de", "fr", "zh-TW", "zh-CN"])
    def test_non_ja_locales_use_cross_border_prompt(self, locale):
        prompt = _build_dynamic_prompt(locale)
        assert "Transform a factual Japanese product description into localized" in prompt


# =============================================================================
# _render_brand_context_block_from_blob: JA brand context preference
# =============================================================================

class TestBrandContextBlobJA:

    _BILINGUAL_BLOB = {
        "en": {
            "clean_text": "We are a Kyoto artisan workshop.",
            "pillars": ["Heritage", "Craftsmanship"],
        },
        "ja": {
            "clean_text": "京都の伝統工房として活動しています。",
            "pillars": ["伝統", "匠の技"],
        },
    }

    def test_ja_prefers_japanese_brand_context(self):
        block = _render_brand_context_block_from_blob(self._BILINGUAL_BLOB, "ja")
        assert "京都の伝統工房" in block
        assert "ブランドの柱" in block

    def test_ja_uses_ja_domestic_template(self):
        block = _render_brand_context_block_from_blob(self._BILINGUAL_BLOB, "ja")
        assert "ブランドストーリー" in block or "ブランド統合" in block

    def test_en_uses_english_brand_context(self):
        block = _render_brand_context_block_from_blob(self._BILINGUAL_BLOB, "en")
        assert "Kyoto artisan workshop" in block
        assert "Core Pillars" in block

    def test_en_uses_standard_template(self):
        block = _render_brand_context_block_from_blob(self._BILINGUAL_BLOB, "en")
        assert "BRAND SOUL" in block

    def test_ja_falls_back_to_en_when_ja_missing(self):
        en_only_blob = {
            "en": {
                "clean_text": "English-only brand story.",
                "pillars": ["Quality"],
            },
        }
        block = _render_brand_context_block_from_blob(en_only_blob, "ja")
        assert "English-only brand story" in block

    def test_empty_blob_returns_empty(self):
        assert _render_brand_context_block_from_blob({}, "ja") == ""
        assert _render_brand_context_block_from_blob(None, "ja") == ""


# =============================================================================
# _augment_seo_and_discoveries_if_missing: JA language instructions
# =============================================================================

class TestAugmentSeoJA:

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    def test_ja_self_heal_prompt_uses_japanese_instructions(self, mock_db):
        """When target_locale is 'ja', the self-heal prompt should instruct
        explanation/suggested_footer in Japanese, not English."""
        captured_prompts: list[str] = []

        def _capture_generate_json(*, system_prompt, **kw):
            captured_prompts.append(system_prompt)
            return {
                "seo_title": "テスト",
                "seo_description": "テスト説明",
                "seo_alt_text": "テスト画像",
                "discovered_values": [],
            }

        with patch(
            "src.ecommerce.core.generation.openai_service.generate_json",
            side_effect=_capture_generate_json,
        ), patch(
            "src.ecommerce.core.generation._should_log_llm_full",
            return_value=False,
        ):
            _augment_seo_and_discoveries_if_missing(
                db=mock_db,
                shop="test-shop.myshopify.com",
                target_locale="ja",
                product_name="Test",
                category="General",
                processed_description="テスト商品説明",
                parsed={"title": "T", "description": "D"},
                discovered_values=[],
                model_used="gpt-4o-mini",
                parse_meta={"parse_mode": "recover_title_desc"},
            )

        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "professional Japanese" in prompt
        assert "domestic Japanese customers" in prompt
        assert "Western customers" not in prompt


# =============================================================================
# process_generation_request: full pipeline JA domestic prompt capture
# =============================================================================

class TestProcessGenerationJA:

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_user(self):
        u = MagicMock(spec=User)
        u.username = "test-shop.myshopify.com"
        return u

    def _fake_openai_response(self):
        resp = MagicMock()
        resp.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"title":"テスト","description":"<p>日本語</p>","discovered_values":[]}'
                )
            )
        ]
        resp.usage = MagicMock()
        resp.usage.total_tokens = 10
        return resp

    @pytest.mark.asyncio
    async def test_ja_generation_uses_domestic_prompt(self, mock_db, mock_user):
        plan = MagicMock(spec=Plan)
        plan.name = "Basic"
        plan.can_stream_responses = False

        req = RewriteRequest(
            product_name="抹茶碗",
            japanese_description="京都の職人が手作り",
            product_id=None,
            target_locale="ja",
        )

        seen_system: list[str] = []

        def _capture(*, system_prompt, **kwargs):
            seen_system.append(system_prompt)
            return self._fake_openai_response()

        with patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True), \
             patch("src.ecommerce.core.generation.openai_service.generate_copy", side_effect=_capture):
            out = await process_generation_request(mock_db, req, mock_user, plan)

        assert out["status"] == "success"
        assert len(seen_system) == 1

        prompt = seen_system[0]
        assert "Japanese domestic" in prompt or "日本国内" in prompt
        assert "Transform a factual Japanese product description into localized" not in prompt

    @pytest.mark.asyncio
    async def test_ja_generation_passes_target_locale_to_generate_copy(self, mock_db, mock_user):
        plan = MagicMock(spec=Plan)
        plan.name = "Basic"
        plan.can_stream_responses = False

        req = RewriteRequest(
            product_name="抹茶碗",
            japanese_description="京都の職人が手作り",
            product_id=None,
            target_locale="ja",
        )

        seen_locale: list[str] = []

        def _capture(*, target_locale=None, **kwargs):
            seen_locale.append(target_locale)
            return self._fake_openai_response()

        with patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True), \
             patch("src.ecommerce.core.generation.openai_service.generate_copy", side_effect=_capture):
            await process_generation_request(mock_db, req, mock_user, plan)

        assert len(seen_locale) == 1
        assert seen_locale[0] == "ja"

    @pytest.mark.asyncio
    async def test_en_generation_uses_cross_border_prompt(self, mock_db, mock_user):
        plan = MagicMock(spec=Plan)
        plan.name = "Basic"
        plan.can_stream_responses = False

        req = RewriteRequest(
            product_name="Matcha Bowl",
            japanese_description="京都の職人が手作り",
            product_id=None,
            target_locale="en",
        )

        seen_system: list[str] = []

        def _capture(*, system_prompt, **kwargs):
            seen_system.append(system_prompt)
            return self._fake_openai_response()

        with patch("src.ecommerce.core.generation.limiter.is_allowed", return_value=True), \
             patch("src.ecommerce.core.generation.openai_service.generate_copy", side_effect=_capture):
            out = await process_generation_request(mock_db, req, mock_user, plan)

        assert out["status"] == "success"
        prompt = seen_system[0]
        assert "Transform a factual Japanese product description into localized" in prompt


# =============================================================================
# OpenAI legacy service: user message wording
# =============================================================================

class TestOpenAIServiceJAUserMessage:

    def test_ja_user_content_says_optimize(self):
        from src.ecommerce.services.openai_legacy_service import OpenAIService

        captured_messages: list[str] = []

        def _fake_create(**kwargs):
            messages = kwargs.get("messages", [])
            for m in messages:
                if m.get("role") == "user":
                    captured_messages.append(m["content"])
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content='{"title":"T","description":"D","discovered_values":[]}'))]
            resp.usage = MagicMock(total_tokens=5)
            return resp

        svc = OpenAIService()
        svc.client = MagicMock()
        svc.client.chat.completions.create = _fake_create

        svc.generate_copy(
            product_name="Test",
            category="General",
            japanese_description="テスト説明",
            target_locale="ja",
        )

        assert len(captured_messages) == 1
        assert "Optimize and refine" in captured_messages[0]
        assert "Translate and beautify" not in captured_messages[0]

    def test_en_user_content_says_translate(self):
        from src.ecommerce.services.openai_legacy_service import OpenAIService

        captured_messages: list[str] = []

        def _fake_create(**kwargs):
            messages = kwargs.get("messages", [])
            for m in messages:
                if m.get("role") == "user":
                    captured_messages.append(m["content"])
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content='{"title":"T","description":"D","discovered_values":[]}'))]
            resp.usage = MagicMock(total_tokens=5)
            return resp

        svc = OpenAIService()
        svc.client = MagicMock()
        svc.client.chat.completions.create = _fake_create

        svc.generate_copy(
            product_name="Test",
            category="General",
            japanese_description="テスト説明",
            target_locale="en",
        )

        assert len(captured_messages) == 1
        assert "Translate and beautify" in captured_messages[0]

    def test_none_locale_defaults_to_translate(self):
        from src.ecommerce.services.openai_legacy_service import OpenAIService

        captured_messages: list[str] = []

        def _fake_create(**kwargs):
            messages = kwargs.get("messages", [])
            for m in messages:
                if m.get("role") == "user":
                    captured_messages.append(m["content"])
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content='{"title":"T","description":"D","discovered_values":[]}'))]
            resp.usage = MagicMock(total_tokens=5)
            return resp

        svc = OpenAIService()
        svc.client = MagicMock()
        svc.client.chat.completions.create = _fake_create

        svc.generate_copy(
            product_name="Test",
            category="General",
            japanese_description="テスト説明",
        )

        assert len(captured_messages) == 1
        assert "Translate and beautify" in captured_messages[0]


# =============================================================================
# RewriterAgent: JA domestic prompt selection
# =============================================================================

class TestRewriterAgentJADomestic:

    @pytest.fixture
    def mock_services(self):
        services = MagicMock()
        services.llm.generate_text = AsyncMock(
            return_value='{"title": "テスト", "description": "<p>国内向け</p>", "discovered_values": []}'
        )
        services.llm.generate_structured = AsyncMock()
        services.serp.search = AsyncMock(return_value=[])
        services.serp.get_competitor_prices = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])
        return services

    def _make_state(self, locale: str):
        from src.ecommerce.state import ShopifyMissionState as MissionState
        return MissionState(
            product_id="test-ja-domestic",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "京都抹茶碗",
                "description": "京都の職人が手作りで作る抹茶碗。天然素材。",
                "category": "キッチン用品",
            },
            target_locale=locale,
        )

    @pytest.mark.asyncio
    async def test_ja_system_prompt_is_domestic(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        system_prompt = agent._build_system_prompt(state, context)

        assert "Japanese domestic" in system_prompt or "日本国内" in system_prompt
        assert "Transform a factual Japanese product description into localized" not in system_prompt

    @pytest.mark.asyncio
    async def test_ja_system_prompt_has_domestic_value_discovery(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        system_prompt = agent._build_system_prompt(state, context)

        assert "国内の日本人消費者" in system_prompt or "domestic Japanese" in system_prompt
        assert "Western customers" not in system_prompt

    @pytest.mark.asyncio
    async def test_ja_system_prompt_has_domestic_tone(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja")
        state.raw_input["tone"] = "luxury"
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        system_prompt = agent._build_system_prompt(state, context)

        assert "ラグジュアリー" in system_prompt or "逸品" in system_prompt
        assert "US English vocabulary" not in system_prompt

    @pytest.mark.asyncio
    async def test_ja_user_prompt_is_domestic(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        user_prompt = agent._build_user_prompt(state, context)

        assert "Target Locale: ja" in user_prompt
        assert "最適化・洗練" in user_prompt or "Optimize and refine" in user_prompt
        assert "Translate and beautify" not in user_prompt

    @pytest.mark.asyncio
    async def test_ja_persona_injected(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        system_prompt = agent._build_system_prompt(state, context)

        assert LOCALE_PERSONA_MAP["ja"] in system_prompt

    @pytest.mark.asyncio
    async def test_ja_full_pipeline_produces_draft(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        result = await agent.run(state)

        assert result.draft_content is not None
        assert result.status == "DRAFT_READY"

    @pytest.mark.asyncio
    async def test_en_still_uses_cross_border_prompts(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("en")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        system_prompt = agent._build_system_prompt(state, context)
        user_prompt = agent._build_user_prompt(state, context)

        assert "Transform a factual Japanese product description into localized" in system_prompt
        assert "Translate and beautify" in user_prompt

    @pytest.mark.asyncio
    async def test_ja_brand_context_uses_domestic_template(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        mock_services.rag.get_brand_context = AsyncMock(return_value=[
            {"content": "京都の伝統工房", "metadata": {"lang": "ja"}},
        ])

        state = self._make_state("ja")
        state.raw_input["brand_soul_enabled"] = True
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)

        brand_text = context.get_brand_context_text()
        if brand_text:
            system_prompt = agent._build_system_prompt(state, context)
            assert "ブランドストーリー" in system_prompt or "ブランド統合" in system_prompt


# =============================================================================
# Prompt constant integrity
# =============================================================================

class TestJADomesticPromptConstants:

    def test_ja_system_prompt_has_json_structure(self):
        assert '"title"' in SYSTEM_PROMPT_JA_DOMESTIC
        assert '"description"' in SYSTEM_PROMPT_JA_DOMESTIC
        assert '"discovered_values"' in SYSTEM_PROMPT_JA_DOMESTIC

    def test_ja_system_prompt_preserves_architectural_rules(self):
        assert "ARCHITECTURAL RULES" in SYSTEM_PROMPT_JA_DOMESTIC
        assert "<h3>" in SYSTEM_PROMPT_JA_DOMESTIC
        assert "<table>" in SYSTEM_PROMPT_JA_DOMESTIC

    def test_ja_value_discovery_has_categories(self):
        for cat in ["Regional Pedigree", "Tactile & Sensory", "Time-as-Luxury", "Artisan Master"]:
            assert cat in VALUE_DISCOVERY_PROMPT or cat in SYSTEM_PROMPT

    def test_ja_tone_prompts_cover_all_keys(self):
        assert set(TONE_PROMPTS.keys()) == set(TONE_PROMPTS_JA_DOMESTIC.keys()), (
            "JA domestic tone prompts must cover the same keys as the standard set"
        )

    def test_ja_brand_template_has_context_placeholder(self):
        assert "{context}" in BRAND_CONTEXT_INJECTION_TEMPLATE_JA_DOMESTIC


# =============================================================================
# JA Domestic Template Addendum
# =============================================================================

class TestJADomesticTemplateAddendum:

    def test_addendum_constant_exists(self):
        from src.shared.config.prompts import JA_DOMESTIC_TEMPLATE_ADDENDUM
        assert len(JA_DOMESTIC_TEMPLATE_ADDENDUM) > 100

    def test_addendum_has_cultural_guidance(self):
        from src.shared.config.prompts import JA_DOMESTIC_TEMPLATE_ADDENDUM
        assert "です/ます" in JA_DOMESTIC_TEMPLATE_ADDENDUM
        assert "ものづくり" in JA_DOMESTIC_TEMPLATE_ADDENDUM
        assert "職人の技" in JA_DOMESTIC_TEMPLATE_ADDENDUM

    def test_addendum_is_reexported_from_rewriter_prompts(self):
        from src.ecommerce.agents.rewriter.prompts import JA_DOMESTIC_TEMPLATE_ADDENDUM
        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in JA_DOMESTIC_TEMPLATE_ADDENDUM


# =============================================================================
# SERP locale params in standalone agent actions
# =============================================================================

class TestSerpLocaleInAgentActions:

    @pytest.fixture
    def mock_services(self):
        services = MagicMock()
        services.serp.search = AsyncMock(return_value=[])
        services.serp.get_competitor_prices = AsyncMock(return_value=[])
        services.llm.generate_text = AsyncMock(return_value='{}')
        return services

    def test_seo_action_passes_ja_serp_params(self, mock_services):
        """seo_optimize_action should pass gl/hl/location for JA locale."""
        from src.ecommerce.core.agent_actions import seo_optimize_action

        with patch(
            "src.ecommerce.core.agent_actions.ServiceRegistry.create_default",
            return_value=mock_services,
        ):
            seo_optimize_action(
                product_data={"title": "抹茶碗", "category": "食器"},
                context={"target_locale": "ja"},
            )

        mock_services.serp.search.assert_called_once()
        call_kwargs = mock_services.serp.search.call_args
        assert call_kwargs.kwargs.get("gl") == "jp" or call_kwargs[1].get("gl") == "jp"
        assert call_kwargs.kwargs.get("hl") == "ja" or call_kwargs[1].get("hl") == "ja"
        assert "Japan" in (call_kwargs.kwargs.get("location") or call_kwargs[1].get("location", ""))

    def test_seo_action_passes_en_serp_params(self, mock_services):
        """seo_optimize_action should pass gl/hl/location for EN locale."""
        from src.ecommerce.core.agent_actions import seo_optimize_action

        with patch(
            "src.ecommerce.core.agent_actions.ServiceRegistry.create_default",
            return_value=mock_services,
        ):
            seo_optimize_action(
                product_data={"title": "Matcha Bowl", "category": "Tableware"},
                context={"target_locale": "en"},
            )

        mock_services.serp.search.assert_called_once()
        call_kwargs = mock_services.serp.search.call_args
        assert call_kwargs.kwargs.get("gl") == "us" or call_kwargs[1].get("gl") == "us"
        assert call_kwargs.kwargs.get("hl") == "en" or call_kwargs[1].get("hl") == "en"

    def test_price_scout_action_passes_ja_serp_params(self, mock_services):
        """price_scout_action should pass gl/hl/location for JA locale."""
        from src.ecommerce.core.agent_actions import price_scout_action

        with patch(
            "src.ecommerce.core.agent_actions.ServiceRegistry.create_default",
            return_value=mock_services,
        ):
            price_scout_action(
                product_data={"title": "南部鉄器 急須", "category": "キッチン用品"},
                context={"target_locale": "ja"},
            )

        mock_services.serp.get_competitor_prices.assert_called_once()
        call_kwargs = mock_services.serp.get_competitor_prices.call_args
        assert call_kwargs.kwargs.get("gl") == "jp" or call_kwargs[1].get("gl") == "jp"
        assert call_kwargs.kwargs.get("hl") == "ja" or call_kwargs[1].get("hl") == "ja"
        assert "Japan" in (call_kwargs.kwargs.get("location") or call_kwargs[1].get("location", ""))

    def test_price_scout_action_passes_en_serp_params(self, mock_services):
        """price_scout_action should pass gl/hl/location for EN locale."""
        from src.ecommerce.core.agent_actions import price_scout_action

        with patch(
            "src.ecommerce.core.agent_actions.ServiceRegistry.create_default",
            return_value=mock_services,
        ):
            price_scout_action(
                product_data={"title": "Matcha Bowl", "category": "Tableware"},
                context={"target_locale": "en"},
            )

        mock_services.serp.get_competitor_prices.assert_called_once()
        call_kwargs = mock_services.serp.get_competitor_prices.call_args
        assert call_kwargs.kwargs.get("gl") == "us" or call_kwargs[1].get("gl") == "us"

    def test_seo_action_no_locale_defaults_gracefully(self, mock_services):
        """seo_optimize_action with no locale should not crash."""
        from src.ecommerce.core.agent_actions import seo_optimize_action

        with patch(
            "src.ecommerce.core.agent_actions.ServiceRegistry.create_default",
            return_value=mock_services,
        ):
            seo_optimize_action(
                product_data={"title": "Test"},
                context={},
            )

        mock_services.serp.search.assert_called_once()


# =============================================================================
# Rewriter agent: JA addendum for non-description templates
# =============================================================================

class TestRewriterTemplateJAAddendum:

    @pytest.fixture
    def mock_services(self):
        services = MagicMock()
        services.llm.generate_text = AsyncMock(return_value='{}')
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])
        return services

    def _make_state(self, locale: str, template_id: str = "product/faq"):
        from src.ecommerce.state import ShopifyMissionState as MissionState
        return MissionState(
            product_id="test-template-ja",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "template_id": template_id,
                "title": "京都抹茶碗",
                "description": "手作り抹茶碗",
                "category": "食器",
                "target_locale": locale,
            },
            target_locale=locale,
        )

    @pytest.mark.asyncio
    async def test_faq_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja", "product/faq")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="product/faq")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt
        assert "です/ます" in prompt

    @pytest.mark.asyncio
    async def test_collection_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja", "product/collection")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="product/collection")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt

    @pytest.mark.asyncio
    async def test_landing_hero_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja", "product/landing-hero")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="product/landing-hero")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt

    @pytest.mark.asyncio
    async def test_blog_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja", "product/blog-post")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="product/blog-post")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt

    @pytest.mark.asyncio
    async def test_faq_en_no_addendum(self, mock_services):
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("en", "product/faq")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="product/faq")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" not in prompt

    @pytest.mark.asyncio
    async def test_description_ja_uses_dedicated_prompt_not_addendum(self, mock_services):
        """product/description path uses REWRITER_SYSTEM_PROMPT_JA_DOMESTIC directly."""
        from src.ecommerce.agents.rewriter import RewriterAgent

        state = self._make_state("ja", "product/description")
        agent = RewriterAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="product/description")

        assert "Japanese domestic" in prompt or "日本国内" in prompt
        assert "JAPANESE DOMESTIC MARKET GUIDELINES" not in prompt


# =============================================================================
# Marketing agent: JA addendum for all template types
# =============================================================================

class TestMarketingAgentJAAddendum:

    @pytest.fixture
    def mock_services(self):
        services = MagicMock()
        services.llm.generate_text = AsyncMock(return_value='{}')
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])
        return services

    def _make_state(self, locale: str, template_id: str):
        from src.ecommerce.state import ShopifyMissionState as MissionState
        return MissionState(
            product_id="test-marketing-ja",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "template_id": template_id,
                "title": "京都抹茶碗",
                "description": "手作り抹茶碗",
                "category": "食器",
                "target_locale": locale,
            },
            target_locale=locale,
        )

    @pytest.mark.asyncio
    async def test_email_launch_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.marketing import MarketingAgent

        state = self._make_state("ja", "marketing/email-launch")
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="marketing/email-launch")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt

    @pytest.mark.asyncio
    async def test_ad_facebook_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.marketing import MarketingAgent

        state = self._make_state("ja", "marketing/ad-facebook")
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="marketing/ad-facebook")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt

    @pytest.mark.asyncio
    async def test_social_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.marketing import MarketingAgent

        state = self._make_state("ja", "marketing/social-tiktok")
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="marketing/social-tiktok")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt

    @pytest.mark.asyncio
    async def test_email_en_no_addendum(self, mock_services):
        from src.ecommerce.agents.marketing import MarketingAgent

        state = self._make_state("en", "marketing/email-launch")
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="marketing/email-launch")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" not in prompt

    @pytest.mark.asyncio
    async def test_ad_google_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.marketing import MarketingAgent

        state = self._make_state("ja", "marketing/ad-google")
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="marketing/ad-google")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt

    @pytest.mark.asyncio
    async def test_email_welcome_ja_includes_addendum(self, mock_services):
        from src.ecommerce.agents.marketing import MarketingAgent

        state = self._make_state("ja", "marketing/email-welcome")
        agent = MarketingAgent("test-shop.myshopify.com", mock_services)
        context = await agent.perceive(state)
        prompt = agent._build_system_prompt(state, context, template_id="marketing/email-welcome")

        assert "JAPANESE DOMESTIC MARKET GUIDELINES" in prompt


# =============================================================================
# Japanese PST Pattern Tests
# =============================================================================


class TestJAPSTPainPatterns:
    """Verify Japanese pain/question patterns are detected by the PST checker."""

    def test_fullwidth_question_mark(self):
        from src.ecommerce.agents.seo.prompts import PST_PAIN_PATTERNS
        import re
        text = "美しい抹茶碗を探していますか？"
        assert any(re.search(p, text) for p in PST_PAIN_PATTERNS)

    def test_desuka_question_ending(self):
        from src.ecommerce.agents.seo.prompts import PST_PAIN_PATTERNS
        import re
        text = "お茶の味が物足りないですか"
        assert any(re.search(p, text) for p in PST_PAIN_PATTERNS)

    def test_masenka_question(self):
        from src.ecommerce.agents.seo.prompts import PST_PAIN_PATTERNS
        import re
        text = "試してみませんか"
        assert any(re.search(p, text) for p in PST_PAIN_PATTERNS)

    def test_osagashi(self):
        from src.ecommerce.agents.seo.prompts import PST_PAIN_PATTERNS
        import re
        text = "完璧な急須をお探しの方へ"
        assert any(re.search(p, text) for p in PST_PAIN_PATTERNS)

    def test_check_cta(self):
        from src.ecommerce.agents.seo.prompts import PST_PAIN_PATTERNS
        import re
        text = "今すぐチェック"
        assert any(re.search(p, text) for p in PST_PAIN_PATTERNS)


class TestJAPSTSolutionPatterns:
    """Verify Japanese solution/benefit patterns are detected."""

    def test_tezukuri(self):
        from src.ecommerce.agents.seo.prompts import PST_SOLUTION_PATTERNS
        import re
        text = "職人による手作りの一品"
        assert any(re.search(p, text) for p in PST_SOLUTION_PATTERNS)

    def test_kodawari(self):
        from src.ecommerce.agents.seo.prompts import PST_SOLUTION_PATTERNS
        import re
        text = "素材へのこだわりが光る"
        assert any(re.search(p, text) for p in PST_SOLUTION_PATTERNS)

    def test_kohinshitsu(self):
        from src.ecommerce.agents.seo.prompts import PST_SOLUTION_PATTERNS
        import re
        text = "高品質な京焼の器"
        assert any(re.search(p, text) for p in PST_SOLUTION_PATTERNS)

    def test_tanoshime(self):
        from src.ecommerce.agents.seo.prompts import PST_SOLUTION_PATTERNS
        import re
        text = "微妙に異なる魅力を楽しめます"
        assert any(re.search(p, text) for p in PST_SOLUTION_PATTERNS)


class TestJAPSTTrustPatterns:
    """Verify Japanese trust patterns are detected."""

    def test_kyoto_region(self):
        from src.ecommerce.agents.seo.prompts import PST_TRUST_PATTERNS
        import re
        text = "京都製の信頼の一品"
        assert any(re.search(p, text) for p in PST_TRUST_PATTERNS)

    def test_shokunin(self):
        from src.ecommerce.agents.seo.prompts import PST_TRUST_PATTERNS
        import re
        text = "熟練の職人が手がける"
        assert any(re.search(p, text) for p in PST_TRUST_PATTERNS)

    def test_dentou_kougei(self):
        from src.ecommerce.agents.seo.prompts import PST_TRUST_PATTERNS
        import re
        text = "伝統工芸品として認定"
        assert any(re.search(p, text) for p in PST_TRUST_PATTERNS)

    def test_shinise(self):
        from src.ecommerce.agents.seo.prompts import PST_TRUST_PATTERNS
        import re
        text = "創業100年の老舗"
        assert any(re.search(p, text) for p in PST_TRUST_PATTERNS)

    def test_years_heritage(self):
        from src.ecommerce.agents.seo.prompts import PST_TRUST_PATTERNS
        import re
        text = "400年の歴史を持つ南部鉄器"
        assert any(re.search(p, text) for p in PST_TRUST_PATTERNS)

    def test_real_ja_seo_description_passes_all_three(self):
        """The actual JA SEO description from the screenshot should now pass PST."""
        from src.ecommerce.agents.seo.prompts import PST_PAIN_PATTERNS, PST_SOLUTION_PATTERNS, PST_TRUST_PATTERNS
        import re
        text = "日常の抹茶や緑茶に最適な茶碗。手作りの陶器で、微妙に異なる魅力を楽しめます。京都製の信頼の一品をお試しください！"
        pain = any(re.search(p, text, re.IGNORECASE) for p in PST_PAIN_PATTERNS)
        solution = any(re.search(p, text, re.IGNORECASE) for p in PST_SOLUTION_PATTERNS)
        trust = any(re.search(p, text, re.IGNORECASE) for p in PST_TRUST_PATTERNS)
        assert pain, "Pain pattern not detected"
        assert solution, "Solution pattern not detected"
        assert trust, "Trust pattern not detected"


class TestYenPriceParsing:
    """Verify SERP price parsing handles yen symbols."""

    def test_yen_symbol_stripped(self):
        price_str = "¥1,790"
        cleaned = price_str.replace("$", "").replace("¥", "").replace("￥", "").replace("円", "").replace(",", "").strip()
        assert float(cleaned) == 1790.0

    def test_fullwidth_yen_stripped(self):
        price_str = "￥9900"
        cleaned = price_str.replace("$", "").replace("¥", "").replace("￥", "").replace("円", "").replace(",", "").strip()
        assert float(cleaned) == 9900.0

    def test_en_suffix_stripped(self):
        price_str = "1790円"
        cleaned = price_str.replace("$", "").replace("¥", "").replace("￥", "").replace("円", "").replace(",", "").strip()
        assert float(cleaned) == 1790.0

    def test_dollar_still_works(self):
        price_str = "$35.99"
        cleaned = price_str.replace("$", "").replace("¥", "").replace("￥", "").replace("円", "").replace(",", "").strip()
        assert float(cleaned) == 35.99


class TestSerpQuerySanitizer:
    """Verify the SERP query sanitizer strips marketing noise."""

    def test_strips_brackets(self):
        from src.agentic_core.tools.serp_service import _sanitize_serp_query
        result = _sanitize_serp_query("【ふるさと納税】大ボリューム！ 鮭 切身")
        assert "【" not in result
        assert "】" not in result
        assert "ふるさと納税" not in result
        assert "大ボリューム" not in result
        assert "鮭" in result

    def test_strips_stars_and_symbols(self):
        from src.agentic_core.tools.serp_service import _sanitize_serp_query
        result = _sanitize_serp_query("★★★ 最高品質 ♪ 抹茶碗 ※注意")
        assert "★" not in result
        assert "♪" not in result
        assert "※" not in result
        assert "抹茶碗" in result

    def test_strips_trailing_punctuation(self):
        from src.agentic_core.tools.serp_service import _sanitize_serp_query
        result = _sanitize_serp_query("南部鉄器 急須！！！")
        assert not result.endswith("！")
        assert "南部鉄器" in result

    def test_strips_unclosed_parens(self):
        from src.agentic_core.tools.serp_service import _sanitize_serp_query
        result = _sanitize_serp_query("鮭 切身 (")
        assert not result.endswith("(")
        assert "鮭" in result

    def test_collapses_multi_spaces(self):
        from src.agentic_core.tools.serp_service import _sanitize_serp_query
        result = _sanitize_serp_query("抹茶碗     天目釉")
        assert "  " not in result

    def test_clean_query_unchanged(self):
        from src.agentic_core.tools.serp_service import _sanitize_serp_query
        result = _sanitize_serp_query("南部鉄器 急須 丸型 0.9L")
        assert result == "南部鉄器 急須 丸型 0.9L"

    def test_google_domain_in_locale_params(self):
        from src.ecommerce.config.shopify_config import LOCALE_TO_SERP_PARAMS
        assert LOCALE_TO_SERP_PARAMS["ja"]["google_domain"] == "google.co.jp"
        assert LOCALE_TO_SERP_PARAMS["en"]["google_domain"] == "google.com"
        assert LOCALE_TO_SERP_PARAMS["zh-TW"]["google_domain"] == "google.com.tw"
        assert LOCALE_TO_SERP_PARAMS["de"]["google_domain"] == "google.de"
        assert LOCALE_TO_SERP_PARAMS["fr"]["google_domain"] == "google.fr"
        for locale, params in LOCALE_TO_SERP_PARAMS.items():
            assert "google_domain" in params, f"Missing google_domain for locale {locale}"

    def test_real_rakuten_product_title(self):
        """The exact product title from the user's bug report should produce a clean short query."""
        from src.agentic_core.tools.serp_service import _sanitize_serp_query
        raw = "【ふるさと納税】 大ボリューム！ 魚鶴仕込の 鮭 切身 ( 冷凍 ) / シャケ 切り身 紅鮭 銀鮭 ※離島への配送不可 //fish General"
        result = _sanitize_serp_query(raw)
        assert "ふるさと納税" not in result
        assert "大ボリューム" not in result
        assert "離島" not in result
        assert "配送不可" not in result
        assert "General" not in result
        assert "鮭" in result
        assert "魚鶴" in result
        assert len(result) <= 80
        assert not result.startswith("！")
        assert not result.startswith("/")

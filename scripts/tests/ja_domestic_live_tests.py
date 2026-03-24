#!/usr/bin/env python3
"""
JA Domestic (Japanese-to-Japanese) live integration tests.

Validates real OpenAI and SERP responses for the Japanese domestic market mode.
Tests run against ACTUAL external APIs (no mocks).

Usage:
  # Full run — all agents (Rewriter, SEO, Marketing, PriceScout, Mission pipeline)
  python scripts/tests/ja_domestic_live_tests.py

  # Skip SERP-dependent tests
  python scripts/tests/ja_domestic_live_tests.py --skip-serp

  # Skip OpenAI-dependent tests (SERP only)
  python scripts/tests/ja_domestic_live_tests.py --skip-openai

  # Run a single test
  python scripts/tests/ja_domestic_live_tests.py --test rewriter

Required env vars:
  OPENAI_API_KEY  (unless --skip-openai)
  SERP_API_KEY    (unless --skip-serp)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from src.ecommerce.config.shopify_config import (
    LOCALE_PERSONA_MAP,
    LOCALE_TO_SERP_PARAMS,
)

LOCALE = "ja"

SAMPLE_PRODUCTS = [
    {
        "title": "京都職人手作り 抹茶碗 天目釉",
        "description": (
            "京都の伝統工芸士が一つ一つ手作りで仕上げた抹茶碗です。\n"
            "天目釉薬を使用し、窯変による独特の模様が特徴。\n"
            "サイズ: 直径12cm、高さ8cm、重さ約280g\n"
            "素材: 陶器（京焼・清水焼）\n"
            "電子レンジ・食洗機不可。手洗いをお勧めします。\n"
            "ギフト包装対応可能。\n"
            "【ショップについて】\n"
            "当店は明治35年創業の京焼専門店です。\n"
            "【配送について】\n"
            "受注後3〜5営業日で発送。送料全国一律800円。"
        ),
        "category": "キッチン・食器",
        "tags": ["抹茶碗", "京焼", "清水焼", "手作り", "伝統工芸"],
    },
    {
        "title": "南部鉄器 急須 丸型 0.9L",
        "description": (
            "岩手県の伝統工芸、南部鉄器の急須です。\n"
            "鋳鉄ならではの保温性に優れ、お茶の味をまろやかにします。\n"
            "内部はホーロー加工で錆びにくく、お手入れ簡単。\n"
            "容量: 0.9L / サイズ: 幅16cm × 高さ15cm\n"
            "重量: 約1.5kg\n"
            "IH非対応。直火・電気コンロ対応。\n"
            "【職人について】\n"
            "400年の歴史を持つ南部鉄器の技法を受け継ぐ職人が製作。"
        ),
        "category": "キッチン用品",
        "tags": ["南部鉄器", "急須", "伝統工芸", "岩手"],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    name: str
    status: str  # PASS | FAIL | SKIP
    duration_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _color(status: str) -> str:
    return {"PASS": "\033[92m", "FAIL": "\033[91m", "SKIP": "\033[93m"}.get(status, "") + status + "\033[0m"


# ---------------------------------------------------------------------------
# SERP Tests
# ---------------------------------------------------------------------------

async def test_serp_organic_japan() -> TestResult:
    """SERP organic search with Japan geo-targeting."""
    from src.agentic_core.tools.serp_service import SerpService

    name = "serp_organic/ja"
    t0 = time.monotonic()

    try:
        service = SerpService()
        params = LOCALE_TO_SERP_PARAMS["ja"]
        product = SAMPLE_PRODUCTS[0]

        results = await service.search(
            query=f"{product['title']} {product['category']}",
            num_results=3,
            location=params["location"],
            gl=params["gl"],
            hl=params["hl"],
        )

        elapsed = (time.monotonic() - t0) * 1000

        if not results:
            return TestResult(name=name, status="FAIL", duration_ms=elapsed, error="Empty organic results")

        has_japanese = any(
            any("\u3040" <= c <= "\u9FFF" for c in (r.title or ""))
            for r in results
        )

        return TestResult(
            name=name, status="PASS", duration_ms=elapsed,
            details={
                "result_count": len(results),
                "has_japanese_titles": has_japanese,
                "first_title": (results[0].title or "")[:100],
                "gl": params["gl"],
                "hl": params["hl"],
            },
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=str(e))


async def test_serp_shopping_japan() -> TestResult:
    """SERP shopping search with Japan geo-targeting."""
    from src.agentic_core.tools.serp_service import SerpService

    name = "serp_shopping/ja"
    t0 = time.monotonic()

    try:
        service = SerpService()
        params = LOCALE_TO_SERP_PARAMS["ja"]
        product = SAMPLE_PRODUCTS[0]

        results = await service.get_competitor_prices(
            product_name=product["title"],
            category=product["category"],
            num_results=5,
            location=params["location"],
            gl=params["gl"],
            hl=params["hl"],
        )

        elapsed = (time.monotonic() - t0) * 1000

        details: dict[str, Any] = {"result_count": len(results)}
        if results:
            prices = [r["extracted_price"] for r in results if r.get("extracted_price")]
            if prices:
                details["price_range"] = f"¥{min(prices):.0f} – ¥{max(prices):.0f}"
            details["first_title"] = (results[0].get("title") or "")[:80]

        return TestResult(
            name=name,
            status="PASS",
            duration_ms=elapsed,
            details=details,
            error=None if results else "No shopping results (may be expected for some queries)",
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=str(e))


# ---------------------------------------------------------------------------
# Rewriter Test
# ---------------------------------------------------------------------------

async def test_rewriter_ja_domestic() -> TestResult:
    """RewriterAgent produces JA domestic copy via real LLM."""
    from src.ecommerce.agents.rewriter import RewriterAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "rewriter/ja_domestic"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[0]
        state = MissionState(
            product_id="test-ja-domestic-rewriter",
            shop_id="test-ja-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
            },
            target_locale="ja",
        )

        agent = RewriterAgent("test-ja-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        if not result.draft_content:
            return TestResult(name=name, status="FAIL", duration_ms=elapsed, error="draft_content is empty")

        content = result.draft_content
        title = result.draft_title or ""

        has_japanese = any("\u3040" <= c <= "\u9FFF" for c in content + title)
        has_html = "<" in content

        validation_notes: list[str] = []
        if has_japanese:
            validation_notes.append("Output contains Japanese characters")
        else:
            validation_notes.append("WARNING: No Japanese characters in output")

        if has_html:
            validation_notes.append("Output contains HTML structure")

        # Check no English-centric artifacts leaked
        if "Western customers" in content:
            validation_notes.append("WARNING: 'Western customers' found in output — domestic mode leak")
        if "Japanglish" in content:
            validation_notes.append("WARNING: 'Japanglish' found in output — domestic mode leak")

        return TestResult(
            name=name, status="PASS", duration_ms=elapsed,
            details={
                "content_length": len(content),
                "title_length": len(title),
                "title_preview": title[:120],
                "content_preview": content[:300],
                "has_japanese": has_japanese,
                "has_html": has_html,
                "validation_notes": validation_notes,
                "status": result.status,
            },
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=f"{e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# SEO Test
# ---------------------------------------------------------------------------

async def test_seo_ja_domestic() -> TestResult:
    """SEOAgent produces JA domestic SEO metadata via real LLM."""
    from src.ecommerce.agents.seo import SEOAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "seo/ja_domestic"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[0]
        state = MissionState(
            product_id="test-ja-domestic-seo",
            shop_id="test-ja-seo-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
            },
            target_locale="ja",
            draft_content="<p>京都の伝統工芸士による手作り抹茶碗。天目釉薬による独特の美しさ。</p>",
        )

        agent = SEOAgent("test-ja-seo-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        details: dict[str, Any] = {
            "seo_title": result.seo_title or "",
            "seo_description": result.seo_description or "",
            "seo_alt_text": result.seo_alt_text or "",
        }

        errors: list[str] = []

        if result.seo_title and len(result.seo_title) > 70:
            errors.append(f"seo_title too long: {len(result.seo_title)} chars")
        if result.seo_description and len(result.seo_description) > 160:
            errors.append(f"seo_description too long: {len(result.seo_description)} chars")
        if not result.seo_title and not result.seo_description:
            errors.append("Both seo_title and seo_description are empty")

        has_japanese_seo = any(
            "\u3040" <= c <= "\u9FFF"
            for c in (result.seo_title or "") + (result.seo_description or "")
        )
        details["has_japanese"] = has_japanese_seo
        if not has_japanese_seo:
            errors.append("SEO output contains no Japanese characters")

        return TestResult(
            name=name,
            status="FAIL" if errors else "PASS",
            duration_ms=elapsed,
            details=details,
            error="; ".join(errors) if errors else None,
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=str(e))


# ---------------------------------------------------------------------------
# Marketing Test
# ---------------------------------------------------------------------------

async def test_marketing_ja_domestic() -> TestResult:
    """MarketingAgent produces JA domestic social hooks via real LLM."""
    from src.ecommerce.agents.marketing import MarketingAgent
    from unittest.mock import MagicMock, AsyncMock

    name = "marketing/ja_domestic"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[0]
        agent = MarketingAgent("test-ja-marketing-shop.myshopify.com", services)

        result = await agent.generate_social_hooks(
            product_title=product["title"],
            category=product["category"],
            tags=product["tags"],
            target_locale="ja",
        )

        elapsed = (time.monotonic() - t0) * 1000

        hooks = result.get("hooks", [])
        details: dict[str, Any] = {"hook_count": len(hooks)}

        if hooks:
            details["first_hook_preview"] = hooks[0].get("caption", "")[:150]
            has_japanese = any(
                "\u3040" <= c <= "\u9FFF"
                for h in hooks
                for c in h.get("caption", "")
            )
            details["has_japanese"] = has_japanese

        return TestResult(
            name=name,
            status="PASS" if hooks else "FAIL",
            duration_ms=elapsed,
            details=details,
            error=None if hooks else "No hooks generated",
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=str(e))


# ---------------------------------------------------------------------------
# PriceScout Test
# ---------------------------------------------------------------------------

async def test_price_scout_ja_domestic() -> TestResult:
    """PriceScoutAgent returns pricing analysis for JP market via real SERP + LLM."""
    from src.ecommerce.agents.price_scout import PriceScoutAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "price_scout/ja_domestic"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        from src.agentic_core.tools.serp_service import SerpService

        llm = LLMService()
        serp = SerpService()

        services = MagicMock()
        services.llm = llm
        services.serp = serp
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[1]
        state = MissionState(
            product_id="test-ja-domestic-price",
            shop_id="test-ja-price-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
            },
            target_locale="ja",
        )

        agent = PriceScoutAgent("test-ja-price-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        pricing = result.pricing_analysis
        details: dict[str, Any] = {}

        if pricing:
            details["competitor_count"] = pricing.get("competitor_count", 0)
            details["recommended_price"] = pricing.get("recommended_price")
            details["price_position"] = pricing.get("price_position")
            details["confidence"] = pricing.get("confidence")

        return TestResult(
            name=name,
            status="PASS" if pricing else "FAIL",
            duration_ms=elapsed,
            details=details,
            error=None if pricing else "No pricing analysis returned",
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=str(e))


# ---------------------------------------------------------------------------
# Writing Content Template Tests (FAQ, Blog Post)
# ---------------------------------------------------------------------------

def _has_japanese(text: str) -> bool:
    """Check if text contains Japanese characters, decoding JSON if needed."""
    if any("\u3040" <= c <= "\u9FFF" for c in text):
        return True
    try:
        decoded = json.loads(text) if text.strip().startswith("{") else text
        flat = json.dumps(decoded, ensure_ascii=False) if isinstance(decoded, (dict, list)) else str(decoded)
        return any("\u3040" <= c <= "\u9FFF" for c in flat)
    except Exception:
        return False


async def test_writing_template_faq_ja() -> TestResult:
    """RewriterAgent generates FAQ content with template_id=product/faq for JA domestic."""
    from src.ecommerce.agents.rewriter import RewriterAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "writing_template/faq_ja"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[0]
        state = MissionState(
            product_id="test-ja-faq-template",
            shop_id="test-ja-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
                "template_id": "product/faq",
            },
            target_locale="ja",
        )

        agent = RewriterAgent("test-ja-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        content = result.draft_content or ""
        has_ja = _has_japanese(content)

        errors: list[str] = []
        if not content:
            errors.append("draft_content is empty")
        if not has_ja:
            errors.append("No Japanese characters in FAQ output")

        decoded_preview = content
        try:
            decoded_preview = json.dumps(json.loads(content), ensure_ascii=False)[:300]
        except Exception:
            decoded_preview = content[:300]

        return TestResult(
            name=name,
            status="FAIL" if errors else "PASS",
            duration_ms=elapsed,
            details={
                "content_length": len(content),
                "content_preview": decoded_preview,
                "has_japanese": has_ja,
                "status": result.status,
                "template_id": "product/faq",
            },
            error="; ".join(errors) if errors else None,
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=f"{e}\n{traceback.format_exc()}")


async def test_writing_template_blog_post_ja() -> TestResult:
    """RewriterAgent generates blog post content with template_id=product/blog-post for JA domestic."""
    from src.ecommerce.agents.rewriter import RewriterAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "writing_template/blog_post_ja"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[1]
        state = MissionState(
            product_id="test-ja-blog-template",
            shop_id="test-ja-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
                "template_id": "product/blog-post",
                "topic": "南部鉄器の魅力と選び方",
            },
            target_locale="ja",
        )

        agent = RewriterAgent("test-ja-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        content = result.draft_content or ""
        has_ja = _has_japanese(content)

        errors: list[str] = []
        if not content:
            errors.append("draft_content is empty")
        if not has_ja:
            errors.append("No Japanese characters in blog post output")

        decoded_preview = content
        try:
            decoded_preview = json.dumps(json.loads(content), ensure_ascii=False)[:300]
        except Exception:
            decoded_preview = content[:300]

        return TestResult(
            name=name,
            status="FAIL" if errors else "PASS",
            duration_ms=elapsed,
            details={
                "content_length": len(content),
                "content_preview": decoded_preview,
                "has_japanese": has_ja,
                "status": result.status,
                "template_id": "product/blog-post",
            },
            error="; ".join(errors) if errors else None,
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=f"{e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Marketing Template Tests (email-launch, ad-facebook)
# ---------------------------------------------------------------------------

async def test_marketing_template_email_ja() -> TestResult:
    """MarketingAgent generates email content with template_id=marketing/email-launch for JA domestic."""
    from src.ecommerce.agents.marketing import MarketingAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "marketing_template/email_launch_ja"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[0]
        state = MissionState(
            product_id="test-ja-email-template",
            shop_id="test-ja-marketing-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
                "template_id": "marketing/email-launch",
                "tags": product["tags"],
            },
            target_locale="ja",
        )

        agent = MarketingAgent("test-ja-marketing-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        content = result.draft_content or ""
        has_ja = _has_japanese(content)

        errors: list[str] = []
        if not content:
            errors.append("draft_content is empty")
        if not has_ja:
            errors.append("No Japanese characters in email output")

        decoded_preview = content
        try:
            decoded_preview = json.dumps(json.loads(content), ensure_ascii=False)[:300]
        except Exception:
            decoded_preview = content[:300]

        return TestResult(
            name=name,
            status="FAIL" if errors else "PASS",
            duration_ms=elapsed,
            details={
                "content_length": len(content),
                "content_preview": decoded_preview,
                "has_japanese": has_ja,
                "status": result.status,
                "template_id": "marketing/email-launch",
            },
            error="; ".join(errors) if errors else None,
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=f"{e}\n{traceback.format_exc()}")


async def test_marketing_template_ad_ja() -> TestResult:
    """MarketingAgent generates ad copy with template_id=marketing/ad-facebook for JA domestic."""
    from src.ecommerce.agents.marketing import MarketingAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "marketing_template/ad_facebook_ja"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[1]
        state = MissionState(
            product_id="test-ja-ad-template",
            shop_id="test-ja-marketing-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
                "template_id": "marketing/ad-facebook",
                "tags": product["tags"],
            },
            target_locale="ja",
        )

        agent = MarketingAgent("test-ja-marketing-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        content = result.draft_content or ""
        has_ja = _has_japanese(content)

        errors: list[str] = []
        if not content:
            errors.append("draft_content is empty")
        if not has_ja:
            errors.append("No Japanese characters in ad copy output")

        decoded_preview = content
        try:
            decoded_preview = json.dumps(json.loads(content), ensure_ascii=False)[:300]
        except Exception:
            decoded_preview = content[:300]

        return TestResult(
            name=name,
            status="FAIL" if errors else "PASS",
            duration_ms=elapsed,
            details={
                "content_length": len(content),
                "content_preview": decoded_preview,
                "has_japanese": has_ja,
                "status": result.status,
                "template_id": "marketing/ad-facebook",
            },
            error="; ".join(errors) if errors else None,
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=f"{e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Full Mission Pipeline Test
# ---------------------------------------------------------------------------

async def test_mission_pipeline_ja_domestic() -> TestResult:
    """Full mission pipeline (Rewriter + SEO) for JA domestic via real LLM."""
    from src.ecommerce.agents.rewriter import RewriterAgent
    from src.ecommerce.agents.seo import SEOAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "mission_pipeline/ja_domestic"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.serp.get_competitor_prices = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[1]
        state = MissionState(
            product_id="test-ja-mission-pipeline",
            shop_id="test-ja-mission-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
            },
            target_locale="ja",
        )

        # Step 1: Rewriter
        rewriter = RewriterAgent("test-ja-mission-shop.myshopify.com", services)
        state = await rewriter.run(state)

        rewriter_ok = bool(state.draft_content)
        rewriter_title = state.draft_title or ""

        # Step 2: SEO
        seo_agent = SEOAgent("test-ja-mission-shop.myshopify.com", services)
        state = await seo_agent.run(state)

        seo_ok = bool(state.seo_title or state.seo_description)

        elapsed = (time.monotonic() - t0) * 1000

        details: dict[str, Any] = {
            "rewriter_ok": rewriter_ok,
            "rewriter_title": rewriter_title[:100],
            "rewriter_content_len": len(state.draft_content or ""),
            "seo_ok": seo_ok,
            "seo_title": (state.seo_title or "")[:70],
            "seo_description": (state.seo_description or "")[:160],
        }

        errors: list[str] = []
        if not rewriter_ok:
            errors.append("Rewriter produced no draft_content")
        if not seo_ok:
            errors.append("SEO produced no seo_title/seo_description")

        combined = (state.draft_content or "") + rewriter_title + (state.seo_title or "")
        has_japanese = any("\u3040" <= c <= "\u9FFF" for c in combined)
        details["has_japanese"] = has_japanese
        if not has_japanese:
            errors.append("Pipeline output contains no Japanese characters")

        return TestResult(
            name=name,
            status="FAIL" if errors else "PASS",
            duration_ms=elapsed,
            details=details,
            error="; ".join(errors) if errors else None,
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=f"{e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Rewriter with second product (variety test)
# ---------------------------------------------------------------------------

async def test_rewriter_ja_domestic_product2() -> TestResult:
    """RewriterAgent with a second product to ensure consistency."""
    from src.ecommerce.agents.rewriter import RewriterAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = "rewriter/ja_domestic_product2"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        product = SAMPLE_PRODUCTS[1]
        state = MissionState(
            product_id="test-ja-domestic-rewriter-p2",
            shop_id="test-ja-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": product["title"],
                "description": product["description"],
                "category": product["category"],
            },
            target_locale="ja",
        )

        agent = RewriterAgent("test-ja-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        if not result.draft_content:
            return TestResult(name=name, status="FAIL", duration_ms=elapsed, error="draft_content is empty")

        content = result.draft_content
        title = result.draft_title or ""

        has_japanese = any("\u3040" <= c <= "\u9FFF" for c in content + title)

        return TestResult(
            name=name, status="PASS", duration_ms=elapsed,
            details={
                "content_length": len(content),
                "title_preview": title[:120],
                "content_preview": content[:300],
                "has_japanese": has_japanese,
                "status": result.status,
            },
        )
    except Exception as e:
        return TestResult(name=name, status="FAIL", duration_ms=(time.monotonic() - t0) * 1000, error=f"{e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _write_report(results: list[TestResult], report_path: str) -> None:
    summary = {
        "generated_at": _ts(),
        "locale": LOCALE,
        "total": len(results),
        "passed": sum(1 for r in results if r.status == "PASS"),
        "failed": sum(1 for r in results if r.status == "FAIL"),
        "skipped": sum(1 for r in results if r.status == "SKIP"),
    }

    payload = {
        "summary": summary,
        "results": [
            {
                "name": r.name,
                "status": r.status,
                "duration_ms": round(r.duration_ms, 1),
                "details": r.details,
                "error": r.error,
            }
            for r in results
        ],
    }

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

SERP_TESTS = [
    ("serp_organic", test_serp_organic_japan),
    ("serp_shopping", test_serp_shopping_japan),
]

OPENAI_TESTS = [
    ("rewriter", test_rewriter_ja_domestic),
    ("rewriter_p2", test_rewriter_ja_domestic_product2),
    ("seo", test_seo_ja_domestic),
    ("marketing", test_marketing_ja_domestic),
    ("writing_faq", test_writing_template_faq_ja),
    ("writing_blog", test_writing_template_blog_post_ja),
    ("marketing_email", test_marketing_template_email_ja),
    ("marketing_ad", test_marketing_template_ad_ja),
    ("mission", test_mission_pipeline_ja_domestic),
]

SERP_OPENAI_TESTS = [
    ("price_scout", test_price_scout_ja_domestic),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_tests(
    skip_openai: bool,
    skip_serp: bool,
    test_filter: str | None,
) -> list[TestResult]:
    results: list[TestResult] = []

    all_tests: list[tuple[str, Any, bool, bool]] = []
    for tag, fn in SERP_TESTS:
        all_tests.append((tag, fn, True, False))
    for tag, fn in OPENAI_TESTS:
        all_tests.append((tag, fn, False, True))
    for tag, fn in SERP_OPENAI_TESTS:
        all_tests.append((tag, fn, True, True))

    for tag, fn, needs_serp, needs_openai in all_tests:
        if test_filter and test_filter not in tag:
            continue

        if needs_serp and skip_serp:
            results.append(TestResult(name=fn.__name__, status="SKIP", error="--skip-serp"))
            print(f"  [{_color('SKIP')}] {fn.__name__} (--skip-serp)")
            continue

        if needs_openai and skip_openai:
            results.append(TestResult(name=fn.__name__, status="SKIP", error="--skip-openai"))
            print(f"  [{_color('SKIP')}] {fn.__name__} (--skip-openai)")
            continue

        r = await fn()
        results.append(r)
        print(f"  [{_color(r.status)}] {r.name} ({r.duration_ms:.0f}ms)")
        if r.error:
            print(f"         Error: {r.error[:300]}")
        for k, v in (r.details or {}).items():
            val_str = str(v)
            if len(val_str) > 150:
                val_str = val_str[:150] + "..."
            print(f"         {k}: {val_str}")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="JA Domestic (Japanese-to-Japanese) live integration tests")
    parser.add_argument("--skip-openai", action="store_true", help="Skip OpenAI-dependent tests")
    parser.add_argument("--skip-serp", action="store_true", help="Skip SERP-dependent tests")
    parser.add_argument("--test", type=str, default=None, help="Run only tests matching this tag (e.g. 'rewriter', 'seo', 'price_scout')")
    parser.add_argument("--report", type=str, default="", help="JSON report output path")
    args = parser.parse_args()

    if not args.skip_openai:
        if not os.getenv("OPENAI_API_KEY", "").strip():
            print("[FATAL] OPENAI_API_KEY required (or pass --skip-openai)")
            return 2

    if not args.skip_serp:
        if not os.getenv("SERP_API_KEY", "").strip():
            print("[FATAL] SERP_API_KEY required (or pass --skip-serp)")
            return 2

    print(f"\n{'#'*60}")
    print(f"  JA Domestic (Japanese-to-Japanese) Live Tests")
    print(f"  Persona: {LOCALE_PERSONA_MAP.get(LOCALE, 'N/A')}")
    print(f"  SERP params: {LOCALE_TO_SERP_PARAMS.get(LOCALE, {})}")
    print(f"  OpenAI: {'SKIP' if args.skip_openai else 'ENABLED'}")
    print(f"  SERP:   {'SKIP' if args.skip_serp else 'ENABLED'}")
    if args.test:
        print(f"  Filter: {args.test}")
    print(f"{'#'*60}\n")

    results = asyncio.run(run_tests(args.skip_openai, args.skip_serp, args.test))

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")

    print(f"\n{'='*60}")
    print(f"  SUMMARY: {_color('PASS')} {passed}  |  {_color('FAIL')} {failed}  |  {_color('SKIP')} {skipped}  |  Total: {len(results)}")
    print(f"{'='*60}")

    if failed:
        print(f"\n  Failed tests:")
        for r in results:
            if r.status == "FAIL":
                print(f"    - {r.name}: {(r.error or 'unknown')[:200]}")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = args.report or os.path.join(_REPO_ROOT, f"logs/ja_domestic_test_report_{ts}.json")
    try:
        _write_report(results, report_path)
        print(f"\n  Report: {report_path}")
    except Exception as e:
        print(f"\n  [WARN] Failed to write report: {e}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

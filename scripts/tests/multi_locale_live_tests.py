#!/usr/bin/env python3
"""
Multi-locale live integration tests.

Validates real OpenAI and SERP responses across all supported locales.
Tests run against ACTUAL external APIs (no mocks).

Usage:
  # Full run — tests all locales against OpenAI + SERP
  python scripts/tests/multi_locale_live_tests.py

  # Skip SERP (OpenAI only)
  python scripts/tests/multi_locale_live_tests.py --skip-serp

  # Skip OpenAI (SERP only)
  python scripts/tests/multi_locale_live_tests.py --skip-openai

  # Test a single locale
  python scripts/tests/multi_locale_live_tests.py --locale ko

  # Quick mode — test only 3 representative locales
  python scripts/tests/multi_locale_live_tests.py --quick

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

# Ensure repo root on path
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

# Representative locales for --quick mode
QUICK_LOCALES = ["en", "ko", "de"]

# Markets where Google Shopping coverage is limited/absent; empty results are expected
LIMITED_SHOPPING_MARKETS = {"ko", "zh-CN", "th", "vi"}

SAMPLE_PRODUCT = {
    "title": "Handcrafted Kyoto Matcha Bowl",
    "description": "京都の職人が手作りで作る抹茶碗。天然素材を使用した伝統的な技法。サイズ: 直径12cm、高さ8cm。",
    "category": "Home & Kitchen",
    "tags": ["matcha", "kyoto", "handmade", "ceramic"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    name: str
    locale: str
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

async def test_serp_organic_search(locale: str) -> TestResult:
    """Test SerpService.search with locale-specific params."""
    from src.agentic_core.tools.serp_service import SerpService

    name = f"serp_organic_search/{locale}"
    t0 = time.monotonic()

    try:
        service = SerpService()
        params = LOCALE_TO_SERP_PARAMS.get(locale, {})

        results = await service.search(
            query=f"{SAMPLE_PRODUCT['title']} {SAMPLE_PRODUCT['category']}",
            num_results=3,
            location=params.get("location"),
            gl=params.get("gl"),
            hl=params.get("hl"),
        )

        elapsed = (time.monotonic() - t0) * 1000

        if not results:
            return TestResult(
                name=name, locale=locale, status="FAIL",
                duration_ms=elapsed,
                error="Empty results — SERP returned no organic results",
                details={"gl": params.get("gl"), "hl": params.get("hl")},
            )

        has_titles = all(r.title for r in results)
        has_links = all(r.link for r in results)

        if not has_titles or not has_links:
            return TestResult(
                name=name, locale=locale, status="FAIL",
                duration_ms=elapsed,
                error="Results missing title or link fields",
                details={"result_count": len(results)},
            )

        return TestResult(
            name=name, locale=locale, status="PASS",
            duration_ms=elapsed,
            details={
                "result_count": len(results),
                "gl": params.get("gl"),
                "hl": params.get("hl"),
                "location": params.get("location"),
                "first_title": results[0].title[:80],
            },
        )

    except Exception as e:
        return TestResult(
            name=name, locale=locale, status="FAIL",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=str(e),
        )


async def test_serp_shopping_search(locale: str) -> TestResult:
    """Test SerpService.search_shopping with locale-specific params."""
    from src.agentic_core.tools.serp_service import SerpService

    name = f"serp_shopping_search/{locale}"
    t0 = time.monotonic()

    try:
        service = SerpService()
        params = LOCALE_TO_SERP_PARAMS.get(locale, {})

        results = await service.get_competitor_prices(
            product_name=SAMPLE_PRODUCT["title"],
            category=SAMPLE_PRODUCT["category"],
            num_results=5,
            location=params.get("location"),
            gl=params.get("gl"),
            hl=params.get("hl"),
        )

        elapsed = (time.monotonic() - t0) * 1000

        details: dict[str, Any] = {
            "result_count": len(results),
            "gl": params.get("gl"),
            "hl": params.get("hl"),
            "location": params.get("location"),
        }

        if results:
            prices = [r["extracted_price"] for r in results if r.get("extracted_price")]
            details["price_range"] = f"${min(prices):.2f} – ${max(prices):.2f}" if prices else "N/A"
            details["first_title"] = results[0].get("title", "")[:80]

        if results:
            status = "PASS"
            error = None
        elif locale in LIMITED_SHOPPING_MARKETS:
            status = "PASS"
            error = None
            details["note"] = "No shopping results (expected for this market — Google Shopping coverage is limited)"
        else:
            status = "FAIL"
            error = "No shopping results returned"

        return TestResult(
            name=name, locale=locale,
            status=status,
            duration_ms=elapsed,
            details=details,
            error=error,
        )

    except Exception as e:
        return TestResult(
            name=name, locale=locale, status="FAIL",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=str(e),
        )


# ---------------------------------------------------------------------------
# OpenAI / LLM Tests
# ---------------------------------------------------------------------------

async def test_rewriter_locale_output(locale: str) -> TestResult:
    """Test RewriterAgent produces locale-appropriate content via real LLM."""
    from src.ecommerce.agents.rewriter import RewriterAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = f"rewriter_locale_output/{locale}"
    t0 = time.monotonic()

    try:
        # Real LLM service, mock everything else
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        state = MissionState(
            product_id="test-locale-product",
            shop_id="test-locale-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": SAMPLE_PRODUCT["title"],
                "description": SAMPLE_PRODUCT["description"],
                "category": SAMPLE_PRODUCT["category"],
            },
            target_locale=locale,
        )

        agent = RewriterAgent("test-locale-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        if not result.draft_content:
            return TestResult(
                name=name, locale=locale, status="FAIL",
                duration_ms=elapsed,
                error="draft_content is empty",
            )

        content = result.draft_content
        title = result.draft_title or ""

        details: dict[str, Any] = {
            "content_length": len(content),
            "title_length": len(title),
            "title_preview": title[:100],
            "content_preview": content[:200],
            "status": result.status,
        }

        # Locale-specific validation heuristics
        validation_ok = True
        validation_notes: list[str] = []

        if locale == "ko":
            has_hangul = any("\uAC00" <= c <= "\uD7A3" for c in content + title)
            if has_hangul:
                validation_notes.append("Contains Korean characters")
            else:
                validation_notes.append("WARNING: No Korean characters found")

        elif locale == "zh-TW":
            has_cjk = any("\u4E00" <= c <= "\u9FFF" for c in content + title)
            if has_cjk:
                validation_notes.append("Contains CJK characters (Traditional Chinese)")
            else:
                validation_notes.append("WARNING: No CJK characters found")

        elif locale == "zh-CN":
            has_cjk = any("\u4E00" <= c <= "\u9FFF" for c in content + title)
            if has_cjk:
                validation_notes.append("Contains CJK characters (Simplified Chinese)")
            else:
                validation_notes.append("WARNING: No CJK characters found")

        elif locale == "de":
            german_hints = ["und", "der", "die", "das", "für", "mit", "von"]
            found = [h for h in german_hints if h.lower() in (content + title).lower()]
            if found:
                validation_notes.append(f"German markers found: {found[:5]}")
            else:
                validation_notes.append("WARNING: No German language markers detected")

        elif locale == "fr":
            french_hints = ["le", "la", "les", "de", "du", "des", "pour", "avec"]
            found = [h for h in french_hints if f" {h.lower()} " in f" {(content + title).lower()} "]
            if found:
                validation_notes.append(f"French markers found: {found[:5]}")
            else:
                validation_notes.append("WARNING: No French language markers detected")

        elif locale == "es":
            spanish_hints = ["el", "la", "los", "las", "de", "del", "con", "para"]
            found = [h for h in spanish_hints if f" {h.lower()} " in f" {(content + title).lower()} "]
            if found:
                validation_notes.append(f"Spanish markers found: {found[:5]}")
            else:
                validation_notes.append("WARNING: No Spanish language markers detected")

        elif locale == "it":
            italian_hints = ["il", "la", "di", "del", "con", "per", "una"]
            found = [h for h in italian_hints if f" {h.lower()} " in f" {(content + title).lower()} "]
            if found:
                validation_notes.append(f"Italian markers found: {found[:5]}")
            else:
                validation_notes.append("WARNING: No Italian language markers detected")

        elif locale == "pt":
            pt_hints = ["o", "a", "de", "do", "da", "com", "para", "um"]
            found = [h for h in pt_hints if f" {h.lower()} " in f" {(content + title).lower()} "]
            if found:
                validation_notes.append(f"Portuguese markers found: {found[:5]}")
            else:
                validation_notes.append("WARNING: No Portuguese language markers detected")

        elif locale == "th":
            has_thai = any("\u0E00" <= c <= "\u0E7F" for c in content + title)
            if has_thai:
                validation_notes.append("Contains Thai characters")
            else:
                validation_notes.append("WARNING: No Thai characters found")

        elif locale == "vi":
            vi_diacritics = "ắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵđ"
            has_vi = any(c in vi_diacritics for c in (content + title).lower())
            if has_vi:
                validation_notes.append("Contains Vietnamese diacritics")
            else:
                validation_notes.append("WARNING: No Vietnamese diacritics found")

        elif locale == "en":
            validation_notes.append("English content (default)")

        details["validation_notes"] = validation_notes

        return TestResult(
            name=name, locale=locale, status="PASS",
            duration_ms=elapsed, details=details,
        )

    except Exception as e:
        return TestResult(
            name=name, locale=locale, status="FAIL",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=f"{e}\n{traceback.format_exc()}",
        )


async def test_seo_locale_output(locale: str) -> TestResult:
    """Test SEOAgent produces locale-appropriate SEO metadata via real LLM."""
    from src.ecommerce.agents.seo import SEOAgent
    from src.ecommerce.state import MissionState
    from unittest.mock import MagicMock, AsyncMock

    name = f"seo_locale_output/{locale}"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        state = MissionState(
            product_id="test-seo-product",
            shop_id="test-seo-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": SAMPLE_PRODUCT["title"],
                "description": SAMPLE_PRODUCT["description"],
                "category": SAMPLE_PRODUCT["category"],
            },
            target_locale=locale,
            draft_content="<p>Beautiful handcrafted matcha bowl from Kyoto artisans.</p>",
        )

        agent = SEOAgent("test-seo-shop.myshopify.com", services)
        result = await agent.run(state)

        elapsed = (time.monotonic() - t0) * 1000

        details: dict[str, Any] = {
            "seo_title": result.seo_title or "",
            "seo_description": result.seo_description or "",
            "seo_alt_text": result.seo_alt_text or "",
        }

        errors: list[str] = []

        if result.seo_title and len(result.seo_title) > 70:
            errors.append(f"seo_title too long: {len(result.seo_title)} chars (max 70)")
        if result.seo_description and len(result.seo_description) > 160:
            errors.append(f"seo_description too long: {len(result.seo_description)} chars (max 160)")

        if not result.seo_title and not result.seo_description:
            errors.append("Both seo_title and seo_description are empty")

        return TestResult(
            name=name, locale=locale,
            status="FAIL" if errors else "PASS",
            duration_ms=elapsed,
            details=details,
            error="; ".join(errors) if errors else None,
        )

    except Exception as e:
        return TestResult(
            name=name, locale=locale, status="FAIL",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=str(e),
        )


async def test_marketing_locale_output(locale: str) -> TestResult:
    """Test MarketingAgent produces social hooks via real LLM."""
    from src.ecommerce.agents.marketing import MarketingAgent
    from unittest.mock import MagicMock, AsyncMock

    name = f"marketing_locale_output/{locale}"
    t0 = time.monotonic()

    try:
        from src.agentic_core.llm.llm_service import LLMService
        llm = LLMService()

        services = MagicMock()
        services.llm = llm
        services.serp.search = AsyncMock(return_value=[])
        services.rag.get_brand_context = AsyncMock(return_value=[])

        agent = MarketingAgent("test-marketing-shop.myshopify.com", services)

        result = await agent.generate_social_hooks(
            product_title=SAMPLE_PRODUCT["title"],
            category=SAMPLE_PRODUCT["category"],
            tags=SAMPLE_PRODUCT["tags"],
        )

        elapsed = (time.monotonic() - t0) * 1000

        hooks = result.get("hooks", [])
        details: dict[str, Any] = {
            "hook_count": len(hooks),
            "locale": locale,
        }
        if hooks:
            details["first_hook_preview"] = hooks[0].get("caption", "")[:100]

        return TestResult(
            name=name, locale=locale,
            status="PASS" if hooks else "FAIL",
            duration_ms=elapsed,
            details=details,
            error=None if hooks else "No hooks generated",
        )

    except Exception as e:
        return TestResult(
            name=name, locale=locale, status="FAIL",
            duration_ms=(time.monotonic() - t0) * 1000,
            error=str(e),
        )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _write_report(results: list[TestResult], report_path: str) -> None:
    summary = {
        "generated_at": _ts(),
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
                "locale": r.locale,
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
# Runner
# ---------------------------------------------------------------------------

async def run_tests(
    locales: list[str],
    skip_openai: bool,
    skip_serp: bool,
) -> list[TestResult]:
    results: list[TestResult] = []

    for locale in locales:
        print(f"\n{'='*60}")
        print(f"  Locale: {locale} ({LOCALE_PERSONA_MAP.get(locale, 'unknown')})")
        print(f"  SERP params: {LOCALE_TO_SERP_PARAMS.get(locale, {})}")
        print(f"{'='*60}")

        # SERP tests
        if skip_serp:
            results.append(TestResult(name=f"serp_organic_search/{locale}", locale=locale, status="SKIP", error="--skip-serp"))
            results.append(TestResult(name=f"serp_shopping_search/{locale}", locale=locale, status="SKIP", error="--skip-serp"))
        else:
            for test_fn in [test_serp_organic_search, test_serp_shopping_search]:
                r = await test_fn(locale)
                results.append(r)
                print(f"  [{_color(r.status)}] {r.name} ({r.duration_ms:.0f}ms)")
                if r.error:
                    print(f"         Error: {r.error[:200]}")
                if r.details:
                    for k, v in r.details.items():
                        print(f"         {k}: {v}")

        # OpenAI tests
        if skip_openai:
            for tname in ["rewriter_locale_output", "seo_locale_output", "marketing_locale_output"]:
                results.append(TestResult(name=f"{tname}/{locale}", locale=locale, status="SKIP", error="--skip-openai"))
        else:
            for test_fn in [test_rewriter_locale_output, test_seo_locale_output, test_marketing_locale_output]:
                r = await test_fn(locale)
                results.append(r)
                print(f"  [{_color(r.status)}] {r.name} ({r.duration_ms:.0f}ms)")
                if r.error:
                    print(f"         Error: {r.error[:200]}")
                for k, v in (r.details or {}).items():
                    val_str = str(v)
                    if len(val_str) > 120:
                        val_str = val_str[:120] + "..."
                    print(f"         {k}: {val_str}")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-locale live integration tests")
    parser.add_argument("--skip-openai", action="store_true", help="Skip OpenAI-dependent tests")
    parser.add_argument("--skip-serp", action="store_true", help="Skip SERP-dependent tests")
    parser.add_argument("--locale", type=str, default=None, help="Test a single locale (e.g. 'ko')")
    parser.add_argument("--quick", action="store_true", help="Test only 3 representative locales (en, ko, de)")
    parser.add_argument("--report", type=str, default="", help="JSON report output path")
    args = parser.parse_args()

    # Validate env
    if not args.skip_openai:
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not openai_key:
            print("[FATAL] OPENAI_API_KEY required (or pass --skip-openai)")
            return 2

    if not args.skip_serp:
        serp_key = os.getenv("SERP_API_KEY", "").strip()
        if not serp_key:
            print("[FATAL] SERP_API_KEY required (or pass --skip-serp)")
            return 2

    # Determine locales
    if args.locale:
        locales = [args.locale]
        if args.locale not in LOCALE_TO_SERP_PARAMS:
            print(f"[WARN] Locale '{args.locale}' not in LOCALE_TO_SERP_PARAMS; SERP params will be empty")
    elif args.quick:
        locales = QUICK_LOCALES
    else:
        locales = list(LOCALE_TO_SERP_PARAMS.keys())

    print(f"\n{'#'*60}")
    print(f"  Multi-Locale Live Integration Tests")
    print(f"  Locales: {', '.join(locales)}")
    print(f"  OpenAI: {'SKIP' if args.skip_openai else 'ENABLED'}")
    print(f"  SERP:   {'SKIP' if args.skip_serp else 'ENABLED'}")
    print(f"{'#'*60}")

    results = asyncio.run(run_tests(locales, args.skip_openai, args.skip_serp))

    # Summary
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
                print(f"    - {r.name}: {r.error or 'unknown error'}")

    # Write report
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = args.report or os.path.join(_REPO_ROOT, f"logs/multi_locale_test_report_{ts}.json")
    try:
        _write_report(results, report_path)
        print(f"\n  Report: {report_path}")
    except Exception as e:
        print(f"\n  [WARN] Failed to write report: {e}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

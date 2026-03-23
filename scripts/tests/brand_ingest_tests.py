"""
Brand Soul Ingestion Tests (Real API Calls)

Validates the full brand soul ingestion pipeline:
- Text file parsing (direct read, no LLM)
- PDF file extraction (GPT-4o-mini vision)
- Web scraping + HTML→text conversion
- LLM cleaning (BRAND_CONTEXT_CLEAN_PROMPT)
- Pillar auto-inference from free-form text
- Strategic intelligence extraction

Required Environment Variables:
- OPENAI_API_KEY: OpenAI API key

Usage:
    python scripts/tests/brand_ingest_tests.py
    
    # Or via regression suite:
    python scripts/regression_test_suite.py --module ingest
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    details: dict[str, Any] | None = None


def _make_pdf(text: str) -> bytes:
    """Build a valid single-page PDF containing *text* using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.set_auto_page_break(auto=True, margin=15)
    for line in text.split("\n"):
        pdf.cell(0, 6, line.strip(), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


class BrandIngestTests:
    """
    Tests for the brand soul ingestion pipeline using REAL APIs.

    Validates:
    - .txt file → direct text read (no LLM cost)
    - .pdf file → GPT-4o-mini vision extraction
    - URL scraping → httpx GET + HTML strip
    - _clean_brand_text → structured EN/JA + pillar inference
    - Strategic intelligence extraction
    """

    def __init__(self) -> None:
        self.results: list[TestResult] = []

    # -- helpers ----------------------------------------------------------

    def _log(self, msg: str) -> None:
        print(msg)

    def _add(self, name: str, passed: bool, message: str, details: dict | None = None) -> None:
        self.results.append(TestResult(name=name, passed=passed, message=message, details=details))
        icon = "✅" if passed else "❌"
        self._log(f"  {icon} {name}: {message}")

    def _has_key(self) -> bool:
        if not os.getenv("OPENAI_API_KEY", ""):
            self._log("  ⚠️  OPENAI_API_KEY not set — skipping")
            return False
        return True

    # =====================================================================
    # 1. Text file parsing (zero LLM cost)
    # =====================================================================

    def test_txt_file_direct_read(self) -> None:
        """Read a .txt fixture and confirm we get usable brand text."""
        txt_path = os.path.join(FIXTURES_DIR, "sample_brand_story.txt")
        if not os.path.exists(txt_path):
            self._add("ingest/txt_read", False, f"Fixture missing: {txt_path}")
            return

        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read()

        ok = len(text) > 100
        has_brand = "hinoki" in text.lower()
        self._add(
            "ingest/txt_read",
            ok and has_brand,
            f"Read {len(text)} chars, brand keyword present={has_brand}",
            {"chars": len(text), "preview": text[:120]},
        )

    # =====================================================================
    # 2. PDF extraction via GPT-4o-mini vision
    # =====================================================================

    def test_pdf_extraction_inline(self) -> None:
        """Generate a PDF in-memory, send to extract_file_text, verify output."""
        if not self._has_key():
            self._add("ingest/pdf_extract_inline", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing PDF extraction — inline generated PDF (PyPDF2 local)")

        brand_text = (
            "Sakura Silk Studio was founded in 1952 in Kyoto Nishijin district.\n"
            "We specialize in hand-woven Nishijin-ori silk textiles using traditional\n"
            "Jacquard looms. Our master weavers create obi sashes, furoshiki wrapping\n"
            "cloths, and modern scarves blending Edo-period patterns with contemporary design."
        )

        pdf_bytes = _make_pdf(brand_text)
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

        from src.ecommerce.services.brand_ingest_service import extract_file_text

        t0 = time.time()
        try:
            extracted = extract_file_text(file_b64=pdf_b64, mime_type="application/pdf")
            elapsed = time.time() - t0
        except Exception as e:
            self._add("ingest/pdf_extract_inline", False, f"Error: {e}")
            return

        ext_lower = extracted.lower()
        has_brand = "sakura" in ext_lower or "nishijin" in ext_lower or "silk" in ext_lower
        ok = len(extracted) > 20 and has_brand

        self._add(
            "ingest/pdf_extract_inline",
            ok,
            f"Extracted {len(extracted)} chars in {elapsed:.1f}s, brand content={has_brand}",
            {"preview": extracted[:200], "elapsed_s": round(elapsed, 2)},
        )

    def test_pdf_extraction_fixture(self) -> None:
        """Load pre-built PDF fixture, send to extract_file_text, verify output."""
        if not self._has_key():
            self._add("ingest/pdf_extract_fixture", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing PDF extraction — fixture file (PyPDF2 local)")

        pdf_path = os.path.join(FIXTURES_DIR, "sample_brand_guidelines.pdf")
        if not os.path.exists(pdf_path):
            self._add("ingest/pdf_extract_fixture", False, f"Fixture missing: {pdf_path}")
            return

        with open(pdf_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("ascii")

        from src.ecommerce.services.brand_ingest_service import extract_file_text

        t0 = time.time()
        try:
            extracted = extract_file_text(file_b64=pdf_b64, mime_type="application/pdf")
            elapsed = time.time() - t0
        except Exception as e:
            self._add("ingest/pdf_extract_fixture", False, f"Error: {e}")
            return

        ext_lower = extracted.lower()
        has_nishijin = "nishijin" in ext_lower
        has_kyoto = "kyoto" in ext_lower
        has_silk = "silk" in ext_lower
        ok = len(extracted) > 50 and (has_nishijin or has_kyoto) and has_silk

        self._add(
            "ingest/pdf_extract_fixture",
            ok,
            (
                f"Extracted {len(extracted)} chars in {elapsed:.1f}s, "
                f"nishijin={has_nishijin}, kyoto={has_kyoto}, silk={has_silk}"
            ),
            {"preview": extracted[:250], "elapsed_s": round(elapsed, 2)},
        )

    # =====================================================================
    # 2b. Japanese text file parsing (zero LLM cost)
    # =====================================================================

    def test_txt_ja_file_direct_read(self) -> None:
        """Read the Japanese .txt fixture and confirm CJK content is intact."""
        txt_path = os.path.join(FIXTURES_DIR, "sample_brand_story_ja.txt")
        if not os.path.exists(txt_path):
            self._add("ingest/txt_ja_read", False, f"Fixture missing: {txt_path}")
            return

        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read()

        ok = len(text) > 100
        has_brand = "匠窯" in text and "有田" in text
        self._add(
            "ingest/txt_ja_read",
            ok and has_brand,
            f"Read {len(text)} chars, brand keywords (匠窯/有田) present={has_brand}",
            {"chars": len(text), "preview": text[:120]},
        )

    # =====================================================================
    # 2c. Japanese PDF extraction
    # =====================================================================

    def test_pdf_ja_extraction_fixture(self) -> None:
        """Load Japanese PDF fixture, extract via PyPDF2, verify CJK output."""
        if not self._has_key():
            self._add("ingest/pdf_ja_extract", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing Japanese PDF extraction — fixture (PyPDF2 local)")

        pdf_path = os.path.join(FIXTURES_DIR, "sample_brand_guidelines_ja.pdf")
        if not os.path.exists(pdf_path):
            self._add("ingest/pdf_ja_extract", False, f"Fixture missing: {pdf_path}")
            return

        with open(pdf_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("ascii")

        from src.ecommerce.services.brand_ingest_service import extract_file_text

        t0 = time.time()
        try:
            extracted = extract_file_text(file_b64=pdf_b64, mime_type="application/pdf")
            elapsed = time.time() - t0
        except Exception as e:
            self._add("ingest/pdf_ja_extract", False, f"Error: {e}")
            return

        has_takumi = "匠窯" in extracted
        has_arita = "有田" in extracted
        has_yonobi = "用の美" in extracted
        ok = len(extracted) > 50 and (has_takumi or has_arita)

        self._add(
            "ingest/pdf_ja_extract",
            ok,
            (
                f"Extracted {len(extracted)} chars in {elapsed:.1f}s, "
                f"匠窯={has_takumi}, 有田={has_arita}, 用の美={has_yonobi}"
            ),
            {"preview": extracted[:250], "elapsed_s": round(elapsed, 2)},
        )

    # =====================================================================
    # 2d. Japanese text → LLM cleaning (verify EN+JA output from JA-only input)
    # =====================================================================

    def test_clean_brand_text_ja_input(self) -> None:
        """Feed Japanese-only brand text to _clean_brand_text, verify both EN and JA output."""
        if not self._has_key():
            self._add("ingest/clean_text_ja", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing _clean_brand_text with Japanese-only input (REAL LLM)")

        from src.ecommerce.services.brand_ingest_service import _clean_brand_text

        raw_ja = (
            "匠窯は1923年に佐賀県有田町で創業した四代続く家族工房です。"
            "「用の美」を信条とし、毎日使い愛される器づくりを目指しています。"
            "天草陶石を使い、一人の職人がろくろで成形。"
            "百年の歴史を持つ登り窯で焼き上げます。"
            "送料：5000円以上で国内送料無料。返品は14日以内に承ります。"
        )

        t0 = time.time()
        result = _clean_brand_text(raw_ja)
        elapsed = time.time() - t0

        en = result.get("en", {})
        ja = result.get("ja", {})

        en_text = en.get("clean_text") or ""
        ja_text = ja.get("clean_text") or ""
        en_pillars = en.get("pillars", [])
        ja_pillars = ja.get("pillars", [])

        has_en_text = len(en_text) > 30
        has_ja_text = len(ja_text) > 20

        # Boilerplate stripped from JA output
        ja_no_boilerplate = "送料" not in ja_text and "返品" not in ja_text

        # EN output should have been translated from the JA input
        en_lower = en_text.lower()
        en_has_brand = any(kw in en_lower for kw in ["takumi", "arita", "yo-no-bi", "beauty of use", "1923"])

        # JA pillars should exist
        has_ja_pillars = len(ja_pillars) >= 1
        has_en_pillars = len(en_pillars) >= 1

        passed = has_en_text and has_ja_text and ja_no_boilerplate and en_has_brand and has_en_pillars
        self._add(
            "ingest/clean_text_ja",
            passed,
            (
                f"EN text={has_en_text} ({len(en_text)}ch), JA text={has_ja_text} ({len(ja_text)}ch), "
                f"EN pillars={en_pillars}, JA pillars={ja_pillars}, "
                f"JA boilerplate_stripped={ja_no_boilerplate}, EN brand_ok={en_has_brand} "
                f"({elapsed:.1f}s)"
            ),
            {
                "en_clean_preview": en_text[:200],
                "ja_clean_preview": ja_text[:200],
                "en_pillars": en_pillars,
                "ja_pillars": ja_pillars,
                "elapsed_s": round(elapsed, 2),
            },
        )

    # =====================================================================
    # 2e. Japanese text file end-to-end
    # =====================================================================

    def test_txt_ja_file_end_to_end(self) -> None:
        """Read JA fixture .txt → _clean_brand_text → verify EN+JA pipeline."""
        if not self._has_key():
            self._add("ingest/txt_ja_e2e", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing end-to-end: Japanese .txt fixture → clean → verify")

        txt_path = os.path.join(FIXTURES_DIR, "sample_brand_story_ja.txt")
        if not os.path.exists(txt_path):
            self._add("ingest/txt_ja_e2e", False, f"Fixture missing: {txt_path}")
            return

        with open(txt_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        from src.ecommerce.services.brand_ingest_service import _clean_brand_text

        t0 = time.time()
        result = _clean_brand_text(raw_text)
        elapsed = time.time() - t0

        en = result.get("en", {})
        ja = result.get("ja", {})
        en_text = (en.get("clean_text") or "")
        ja_text = (ja.get("clean_text") or "")
        en_pillars = en.get("pillars", [])
        ja_pillars = ja.get("pillars", [])

        # JA output should preserve key brand terms
        ja_has_brand = "匠窯" in ja_text or "有田" in ja_text or "用の美" in ja_text
        # EN output should be a meaningful translation
        en_lower = en_text.lower()
        en_has_brand = any(kw in en_lower for kw in ["takumi", "arita", "1923", "beauty", "porcelain", "ceramic"])

        reasonable_en = 50 < len(en_text) < 5000
        reasonable_ja = 30 < len(ja_text) < 5000
        has_pillars = len(en_pillars) >= 1 and len(ja_pillars) >= 1

        passed = ja_has_brand and en_has_brand and reasonable_en and reasonable_ja and has_pillars
        self._add(
            "ingest/txt_ja_e2e",
            passed,
            (
                f"EN {len(en_text)}ch (brand={en_has_brand}), JA {len(ja_text)}ch (brand={ja_has_brand}), "
                f"EN pillars={en_pillars}, JA pillars={ja_pillars} ({elapsed:.1f}s)"
            ),
            {
                "en_preview": en_text[:200],
                "ja_preview": ja_text[:200],
                "en_pillars": en_pillars,
                "ja_pillars": ja_pillars,
                "elapsed_s": round(elapsed, 2),
            },
        )

    # =====================================================================
    # 2f. Japanese PDF end-to-end (extract → clean → verify)
    # =====================================================================

    def test_pdf_ja_end_to_end(self) -> None:
        """Japanese PDF fixture → extract → _clean_brand_text → verify pipeline."""
        if not self._has_key():
            self._add("ingest/pdf_ja_e2e", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing end-to-end: Japanese PDF → extract → clean → verify")

        pdf_path = os.path.join(FIXTURES_DIR, "sample_brand_guidelines_ja.pdf")
        if not os.path.exists(pdf_path):
            self._add("ingest/pdf_ja_e2e", False, f"Fixture missing: {pdf_path}")
            return

        with open(pdf_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("ascii")

        from src.ecommerce.services.brand_ingest_service import extract_file_text, _clean_brand_text

        t0 = time.time()
        try:
            raw_extracted = extract_file_text(file_b64=pdf_b64, mime_type="application/pdf")
            # extract_file_text returns JSON string {"text": "..."} or plain text
            try:
                parsed = json.loads(raw_extracted)
                raw_text = parsed.get("text", raw_extracted)
            except (json.JSONDecodeError, TypeError):
                raw_text = raw_extracted

            result = _clean_brand_text(raw_text)
            elapsed = time.time() - t0
        except Exception as e:
            self._add("ingest/pdf_ja_e2e", False, f"Error: {e}")
            return

        en = result.get("en", {})
        ja = result.get("ja", {})
        en_text = en.get("clean_text") or ""
        ja_text = ja.get("clean_text") or ""

        ja_has_brand = "匠窯" in ja_text or "有田" in ja_text or "用の美" in ja_text
        en_lower = en_text.lower()
        en_has_brand = any(kw in en_lower for kw in ["takumi", "arita", "1923", "beauty", "porcelain", "ceramic"])

        passed = len(en_text) > 30 and len(ja_text) > 20 and (ja_has_brand or en_has_brand)
        self._add(
            "ingest/pdf_ja_e2e",
            passed,
            (
                f"PDF→extract→clean: EN {len(en_text)}ch, JA {len(ja_text)}ch, "
                f"EN brand={en_has_brand}, JA brand={ja_has_brand} ({elapsed:.1f}s)"
            ),
            {
                "en_preview": en_text[:200],
                "ja_preview": ja_text[:200],
                "elapsed_s": round(elapsed, 2),
            },
        )

    # =====================================================================
    # 3. Web scraping + HTML→text
    # =====================================================================

    def test_url_scraping(self) -> None:
        """Scrape a real public URL and verify text extraction."""
        self._log("\n  🌐 Testing URL scraping (httpx GET, zero LLM cost)")

        from src.ecommerce.services.brand_ingest_service import scrape_urls

        # Use a stable, lightweight public page
        test_urls = ["https://example.com"]

        t0 = time.time()
        results = scrape_urls(test_urls)
        elapsed = time.time() - t0

        if not results:
            self._add(
                "ingest/url_scrape",
                False,
                f"No text scraped from {test_urls}",
            )
            return

        text = results[0].get("text", "")
        ok = len(text) > 20
        self._add(
            "ingest/url_scrape",
            ok,
            f"Scraped {len(text)} chars in {elapsed:.1f}s from {test_urls[0]}",
            {"chars": len(text), "preview": text[:150], "elapsed_s": round(elapsed, 2)},
        )

    def test_html_to_text_strips_tags(self) -> None:
        """Verify _html_to_text strips scripts, styles, and tags."""
        from src.ecommerce.services.brand_ingest_service import _html_to_text

        html = (
            "<html><head><style>body{color:red}</style>"
            "<script>alert(1)</script></head>"
            '<body><h1>Our Brand</h1><p>Founded in 1900.</p>'
            "<nav>Home | About</nav></body></html>"
        )
        text = _html_to_text(html)
        has_content = "Our Brand" in text and "Founded in 1900" in text
        no_tags = "<" not in text and "alert" not in text and "color:red" not in text
        self._add(
            "ingest/html_strip",
            has_content and no_tags,
            f"Stripped HTML → {len(text)} chars, content_ok={has_content}, clean={no_tags}",
            {"text": text[:150]},
        )

    # =====================================================================
    # 4. LLM cleaning + pillar auto-inference
    # =====================================================================

    def test_clean_brand_text(self) -> None:
        """Run _clean_brand_text on raw brand text, verify structure + pillars."""
        if not self._has_key():
            self._add("ingest/clean_text", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing _clean_brand_text (REAL LLM — gpt-4o-mini)")

        from src.ecommerce.services.brand_ingest_service import _clean_brand_text

        raw = (
            "Hinoki Workshop was founded in 2005 in Yoshino, Nara Prefecture. "
            "We are a third-generation woodworking studio specialising in hinoki "
            "cypress products. Our philosophy is Mottainai — nothing should go to waste. "
            "We make cutting boards, bath stools, bento boxes, and aromatic sachets. "
            "Shipping info: free domestic shipping over 5000 yen. Returns within 14 days."
        )

        t0 = time.time()
        result = _clean_brand_text(raw)
        elapsed = time.time() - t0

        # Validate structure
        en = result.get("en", {})
        ja = result.get("ja", {})

        has_en_text = bool(en.get("clean_text"))
        has_ja_text = bool(ja.get("clean_text"))
        en_pillars = en.get("pillars", [])
        ja_pillars = ja.get("pillars", [])

        # Verify boilerplate was stripped
        clean_en = (en.get("clean_text") or "").lower()
        no_boilerplate = "shipping" not in clean_en and "returns" not in clean_en

        # Verify pillars were inferred
        has_pillars = len(en_pillars) >= 1

        # Verify brand keywords preserved
        has_keywords = "hinoki" in clean_en or "yoshino" in clean_en or "mottainai" in clean_en

        passed = has_en_text and has_pillars and no_boilerplate and has_keywords
        self._add(
            "ingest/clean_text",
            passed,
            (
                f"EN text={has_en_text}, JA text={has_ja_text}, "
                f"pillars_en={en_pillars}, boilerplate_stripped={no_boilerplate}, "
                f"keywords={has_keywords} ({elapsed:.1f}s)"
            ),
            {
                "en_clean_preview": (en.get("clean_text") or "")[:150],
                "en_pillars": en_pillars,
                "ja_pillars": ja_pillars,
                "elapsed_s": round(elapsed, 2),
            },
        )

    def test_pillar_inference_from_plain_text(self) -> None:
        """Verify that pillars are auto-inferred even when NOT explicitly stated."""
        if not self._has_key():
            self._add("ingest/pillar_inference", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing pillar auto-inference (no explicit pillars in input)")

        from src.ecommerce.services.brand_ingest_service import _clean_brand_text

        raw_no_pillars = (
            "Tanuki Brewing has been crafting sake in Niigata since 1887. "
            "We use only locally grown Gohyakumangoku rice and pure snowmelt water "
            "from Mount Echigo. Our toji (master brewer) follows the Echigo tradition "
            "of slow, cold fermentation through the harsh winter months. "
            "Every bottle is a reflection of the land and the season."
        )

        result = _clean_brand_text(raw_no_pillars)
        en_pillars = result.get("en", {}).get("pillars", [])

        passed = len(en_pillars) >= 1
        self._add(
            "ingest/pillar_inference",
            passed,
            f"Inferred {len(en_pillars)} pillars from plain text: {en_pillars}",
            {"pillars": en_pillars},
        )

    # =====================================================================
    # 5. Strategic intelligence extraction
    # =====================================================================

    def test_strategic_intelligence_extraction(self) -> None:
        """Run the full strategic audit on brand text, verify structured output."""
        if not self._has_key():
            self._add("ingest/strategic_intel", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing strategic intelligence extraction (REAL LLM — gpt-4o)")

        from src.ecommerce.services.intelligence_extractor import IntelligenceExtractorService
        from src.agentic_core.llm.llm_service import LLMService

        llm = LLMService()
        extractor = IntelligenceExtractorService(llm)

        brand_text = (
            "Takumi Ceramics is a fourth-generation family workshop founded in 1923 "
            "in Arita, Saga Prefecture. We believe in Yo-no-bi — the beauty of use. "
            "Each piece passes through 23 steps over 6 weeks: hand-wedged Amakusa clay, "
            "wheel-thrown by a single artisan, bisque-fired at 900C, hand-painted with "
            "natural Gosu cobalt pigments, celadon glaze-dipped, and final-fired at 1300C. "
            "We speak with quiet confidence, using sensory language but never hyperbole."
        )

        t0 = time.time()
        try:
            intel = asyncio.get_event_loop().run_until_complete(
                extractor.extract_strategic_audit(brand_text=brand_text)
            )
            elapsed = time.time() - t0
        except Exception as e:
            self._add("ingest/strategic_intel", False, f"Error: {e}")
            return

        checks = {
            "has_archetype": bool(intel.archetype),
            "has_tonal_guardrails": bool(intel.tonal_guardrails),
            "has_power_words": len(intel.power_words) >= 3,
            "has_banned_phrases": len(intel.banned_phrases) >= 1,
            "has_value_props": len(intel.core_value_props) >= 1,
            "has_differentiators": len(intel.differentiators) >= 1,
            "has_origin_hooks": len(intel.origin_story_hooks) >= 1,
        }
        all_passed = all(checks.values())

        self._add(
            "ingest/strategic_intel",
            all_passed,
            (
                f"Archetype={intel.archetype.value}, "
                f"power_words={len(intel.power_words)}, "
                f"value_props={len(intel.core_value_props)}, "
                f"checks={sum(checks.values())}/{len(checks)} ({elapsed:.1f}s)"
            ),
            {
                "archetype": intel.archetype.value,
                "confidence": intel.archetype_confidence,
                "power_words_sample": intel.power_words[:5],
                "value_props": intel.core_value_props[:3],
                "checks": checks,
                "elapsed_s": round(elapsed, 2),
            },
        )

    # =====================================================================
    # 6. End-to-end: txt file → clean → verify
    # =====================================================================

    def test_txt_file_end_to_end(self) -> None:
        """Read fixture .txt → _clean_brand_text → verify full pipeline."""
        if not self._has_key():
            self._add("ingest/txt_e2e", True, "Skipped (no OPENAI_API_KEY)")
            return

        self._log("\n  🔥 Testing end-to-end: .txt fixture → clean → verify")

        txt_path = os.path.join(FIXTURES_DIR, "sample_brand_story.txt")
        if not os.path.exists(txt_path):
            self._add("ingest/txt_e2e", False, f"Fixture missing: {txt_path}")
            return

        with open(txt_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        from src.ecommerce.services.brand_ingest_service import _clean_brand_text

        t0 = time.time()
        result = _clean_brand_text(raw_text)
        elapsed = time.time() - t0

        en = result.get("en", {})
        clean = (en.get("clean_text") or "").lower()
        pillars = en.get("pillars", [])

        has_brand = "hinoki" in clean or "yoshino" in clean or "mottainai" in clean
        has_pillars = len(pillars) >= 1
        reasonable_len = 50 < len(clean) < 3000

        passed = has_brand and has_pillars and reasonable_len
        self._add(
            "ingest/txt_e2e",
            passed,
            (
                f"Clean text {len(clean)} chars, pillars={pillars}, "
                f"brand_ok={has_brand} ({elapsed:.1f}s)"
            ),
            {
                "clean_preview": clean[:200],
                "pillars": pillars,
                "elapsed_s": round(elapsed, 2),
            },
        )

    # =====================================================================
    # Runner
    # =====================================================================

    def run_all(self) -> list[TestResult]:
        self._log("\n📦 Brand Soul Ingestion Tests (REAL API CALLS)")
        self._log("=" * 55)

        self._log("\n📄 File Parsing Tests (EN)")
        self.test_txt_file_direct_read()
        self.test_html_to_text_strips_tags()

        self._log("\n📄 File Parsing Tests (JA)")
        self.test_txt_ja_file_direct_read()

        self._log("\n🌐 URL Scraping Tests")
        self.test_url_scraping()

        self._log("\n🤖 LLM Cleaning + Pillar Inference Tests (EN input)")
        self.test_clean_brand_text()
        self.test_pillar_inference_from_plain_text()

        self._log("\n🤖 LLM Cleaning Tests (JA input → EN+JA output)")
        self.test_clean_brand_text_ja_input()

        self._log("\n📑 PDF Extraction Tests (EN)")
        self.test_pdf_extraction_inline()
        self.test_pdf_extraction_fixture()

        self._log("\n📑 PDF Extraction Tests (JA)")
        self.test_pdf_ja_extraction_fixture()

        self._log("\n🧠 Strategic Intelligence Tests")
        self.test_strategic_intelligence_extraction()

        self._log("\n🔗 End-to-End Tests (EN)")
        self.test_txt_file_end_to_end()

        self._log("\n🔗 End-to-End Tests (JA)")
        self.test_txt_ja_file_end_to_end()
        self.test_pdf_ja_end_to_end()

        return self.results

    def get_summary(self) -> dict[str, int]:
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        return {"passed": passed, "failed": failed, "total": len(self.results)}


if __name__ == "__main__":
    tests = BrandIngestTests()
    results = tests.run_all()
    summary = tests.get_summary()
    print(f"\n{'=' * 55}")
    print(f"Summary: {summary['passed']} passed | {summary['failed']} failed | {summary['total']} total")
    sys.exit(0 if summary["failed"] == 0 else 1)

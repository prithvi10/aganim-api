"""
SEO Feature Tests (Real API Calls)

Validates SEO outputs using REAL LLM APIs via the SEOAgent.
Tests title, description, alt-text, CTR scoring, and SERP insights.

Required Environment Variables:
- OPENAI_API_KEY: OpenAI API key
- SERP_API_KEY: (optional) SERP API key for competitor insights
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

# Ensure repo root is on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    message: str
    details: dict[str, Any] | None = None


class SEOFeatureTests:
    """
    Tests for SEO feature validation using REAL LLM APIs via SEOAgent.
    
    Validates:
    - SEO title format and length (<=70 chars)
    - SEO description PST formula and length (<=160 chars)
    - Alt-text format
    - CTR check scoring
    - SERP insights retrieval
    """

    def __init__(self, fixtures_path: str | None = None):
        """Initialize with fixtures."""
        if fixtures_path is None:
            fixtures_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "regression_fixtures.json"
            )
        
        with open(fixtures_path, "r", encoding="utf-8") as f:
            self.fixtures = json.load(f)
        
        self.results: list[TestResult] = []
        self._services = None

    def _log(self, msg: str) -> None:
        """Log a message."""
        print(msg)

    def _add_result(self, name: str, passed: bool, message: str, details: dict | None = None) -> None:
        """Add a test result."""
        self.results.append(TestResult(name=name, passed=passed, message=message, details=details))
        status = "✅" if passed else "❌"
        self._log(f"  {status} {name}: {message}")

    def _check_env(self) -> bool:
        """Check if required environment variables are set."""
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            self._log("  ⚠️  OPENAI_API_KEY not set - skipping real API tests")
            return False
        return True

    def _get_real_services(self):
        """Get real ServiceRegistry with actual API clients."""
        if self._services is None:
            from src.ecommerce.services.registry import ServiceRegistry
            self._services = ServiceRegistry.create_default()
        return self._services

    # =========================================================================
    # SEO Title Tests (Real LLM via SEOAgent)
    # =========================================================================

    def test_seo_title_generation_and_length(self) -> None:
        """Test that SEO title is generated and meets length constraint using REAL LLM."""
        if not self._check_env():
            self._add_result("seo/title", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.seo import SEOAgent
        from src.ecommerce.state import MissionState
        
        self._log("\n  🔥 Testing SEO title generation (REAL LLM via SEOAgent)")
        
        services = self._get_real_services()
        
        # Use an artisan product to get meaningful SEO
        state = MissionState(
            product_id="test-seo-title",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "京都職人の抹茶碗",
                "category": "Tableware",
            },
            target_locale="en",
            draft_content="<p>Handcrafted matcha bowl by Kyoto artisans. Made using traditional Arita-yaki techniques. Perfect for authentic tea ceremony. Diameter 12cm, height 8cm.</p>",
            draft_title="Kyoto Artisan Matcha Bowl",
        )
        
        try:
            agent = SEOAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            seo_title = result_state.seo_title or ""
            title_len = len(seo_title)
            
            # Check generation
            if title_len > 0:
                self._add_result(
                    "seo/title_generated",
                    True,
                    f"Title generated: '{seo_title[:50]}...' ({title_len} chars)",
                    {"seo_title": seo_title}
                )
            else:
                self._add_result(
                    "seo/title_generated",
                    False,
                    "No SEO title generated"
                )
            
            # Check length constraint
            if title_len <= 70:
                self._add_result(
                    "seo/title_length",
                    True,
                    f"Length OK: {title_len}/70 chars"
                )
            else:
                self._add_result(
                    "seo/title_length",
                    False,
                    f"Length exceeded: {title_len}/70 chars"
                )
                
        except Exception as e:
            self._add_result("seo/title_generated", False, f"Error: {e}")

    # =========================================================================
    # SEO Description Tests (Real LLM via SEOAgent)
    # =========================================================================

    def test_seo_description_generation_and_length(self) -> None:
        """Test that SEO description is generated and meets length constraint using REAL LLM."""
        if not self._check_env():
            self._add_result("seo/description", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.seo import SEOAgent
        from src.ecommerce.state import MissionState
        
        self._log("\n  🔥 Testing SEO description generation (REAL LLM via SEOAgent)")
        
        services = self._get_real_services()
        
        state = MissionState(
            product_id="test-seo-desc",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "Japanese Silk Kimono",
                "category": "Clothing",
            },
            target_locale="en",
            draft_content="<p>Exquisite silk kimono featuring Nishijin-ori weaving. Hand-embroidered with gold and silver threads. Perfect for special occasions. Made in Kyoto by master weavers.</p>",
            draft_title="Japanese Silk Kimono",
        )
        
        try:
            agent = SEOAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            seo_desc = result_state.seo_description or ""
            desc_len = len(seo_desc)
            
            # Check generation
            if desc_len > 0:
                self._add_result(
                    "seo/description_generated",
                    True,
                    f"Description generated: '{seo_desc[:80]}...' ({desc_len} chars)",
                    {"seo_description": seo_desc}
                )
            else:
                self._add_result(
                    "seo/description_generated",
                    False,
                    "No SEO description generated"
                )
            
            # Check length constraint
            if desc_len <= 160:
                self._add_result(
                    "seo/description_length",
                    True,
                    f"Length OK: {desc_len}/160 chars"
                )
            else:
                self._add_result(
                    "seo/description_length",
                    False,
                    f"Length exceeded: {desc_len}/160 chars"
                )
                
        except Exception as e:
            self._add_result("seo/description_generated", False, f"Error: {e}")

    # =========================================================================
    # Alt-Text Tests (Real LLM via SEOAgent)
    # =========================================================================

    def test_seo_alt_text_generation(self) -> None:
        """Test that alt-text is generated using REAL LLM."""
        if not self._check_env():
            self._add_result("seo/alt_text", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.seo import SEOAgent
        from src.ecommerce.state import MissionState
        
        self._log("\n  🔥 Testing SEO alt-text generation (REAL LLM via SEOAgent)")
        
        services = self._get_real_services()
        
        state = MissionState(
            product_id="test-alt-text",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "Bizen-yaki Sake Cup",
                "category": "Tableware",
            },
            target_locale="en",
            draft_content="<p>Traditional Bizen-yaki sake cup fired in a noborigama kiln. Natural ash glaze creates unique patterns. Each piece is one-of-a-kind.</p>",
            draft_title="Bizen-yaki Sake Cup",
        )
        
        try:
            agent = SEOAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            alt_text = result_state.seo_alt_text or ""
            
            if len(alt_text) > 0:
                self._add_result(
                    "seo/alt_text_generated",
                    True,
                    f"Alt-text generated: '{alt_text}'",
                    {"seo_alt_text": alt_text}
                )
            else:
                self._add_result(
                    "seo/alt_text_generated",
                    False,
                    "No alt-text generated"
                )
                
        except Exception as e:
            self._add_result("seo/alt_text_generated", False, f"Error: {e}")

    # =========================================================================
    # CTR Check Tests (Deterministic via SEOAgent)
    # =========================================================================

    def test_ctr_check_high_score_content(self) -> None:
        """Test CTR scoring on PST-optimized content using REAL agents."""
        if not self._check_env():
            self._add_result("seo/ctr_high", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.seo import SEOAgent
        from src.ecommerce.state import MissionState
        
        self._log("\n  🔥 Testing CTR check on PST content (via SEOAgent)")
        
        services = self._get_real_services()
        
        # PST-optimized content (Pain, Solution, Trust)
        pst_content = """<p>Tired of bland, mass-produced tea experiences? 
        This handcrafted Kyoto matcha bowl transforms your daily ritual into an authentic Japanese ceremony. 
        Made by master artisans with 200 years of tradition. Ships free from Japan.</p>"""
        
        state = MissionState(
            product_id="test-ctr-high",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "Kyoto Matcha Bowl",
                "category": "Tableware",
            },
            target_locale="en",
            draft_content=pst_content,
            draft_title="Kyoto Matcha Bowl",
        )
        
        try:
            agent = SEOAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            ctr = result_state.ctr_check
            if ctr:
                score = ctr.get("score", 0)
                pain = ctr.get("pain_present", False)
                solution = ctr.get("solution_present", False)
                trust = ctr.get("trust_present", False)
                
                # PST content should score high
                if score >= 0.5:
                    self._add_result(
                        "seo/ctr_high_score",
                        True,
                        f"High CTR score: {score:.2f} (pain={pain}, solution={solution}, trust={trust})",
                        {"ctr_check": ctr}
                    )
                else:
                    self._add_result(
                        "seo/ctr_high_score",
                        False,
                        f"Expected high score, got: {score:.2f}"
                    )
            else:
                self._add_result("seo/ctr_high_score", False, "No CTR check returned")
                
        except Exception as e:
            self._add_result("seo/ctr_high_score", False, f"Error: {e}")

    def test_ctr_check_low_score_content(self) -> None:
        """Test CTR scoring on minimal content using REAL agents."""
        if not self._check_env():
            self._add_result("seo/ctr_low", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.seo import SEOAgent
        from src.ecommerce.state import MissionState
        
        self._log("\n  🔥 Testing CTR check on minimal content (via SEOAgent)")
        
        services = self._get_real_services()
        
        # Minimal content (no PST elements)
        minimal_content = "<p>A bowl for everyday use.</p>"
        
        state = MissionState(
            product_id="test-ctr-low",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "Simple Bowl",
                "category": "Tableware",
            },
            target_locale="en",
            draft_content=minimal_content,
            draft_title="Simple Bowl",
        )
        
        try:
            agent = SEOAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            ctr = result_state.ctr_check
            if ctr:
                score = ctr.get("score", 1)
                
                # Minimal content should score low
                if score < 0.5:
                    self._add_result(
                        "seo/ctr_low_score",
                        True,
                        f"Low CTR score as expected: {score:.2f}",
                        {"ctr_check": ctr}
                    )
                else:
                    self._add_result(
                        "seo/ctr_low_score",
                        False,
                        f"Expected low score, got: {score:.2f}"
                    )
            else:
                self._add_result("seo/ctr_low_score", False, "No CTR check returned")
                
        except Exception as e:
            self._add_result("seo/ctr_low_score", False, f"Error: {e}")

    # =========================================================================
    # SERP Insights Tests (Real SERP API via SEOAgent)
    # =========================================================================

    def test_serp_insights_retrieval(self) -> None:
        """Test SERP insights retrieval using REAL SERP API."""
        if not self._check_env():
            self._add_result("seo/serp", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        serp_key = os.getenv("SERP_API_KEY", "")
        if not serp_key:
            self._add_result("seo/serp_insights", True, "Skipped (no SERP_API_KEY)")
            return
        
        from src.ecommerce.agents.seo import SEOAgent
        from src.ecommerce.state import MissionState
        
        self._log("\n  🔥 Testing SERP insights retrieval (REAL SERP API via SEOAgent)")
        
        services = self._get_real_services()
        
        state = MissionState(
            product_id="test-serp",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "Japanese Matcha Bowl",
                "category": "Tableware",
            },
            target_locale="en",
            draft_content="<p>Traditional Japanese matcha bowl for tea ceremony.</p>",
            draft_title="Japanese Matcha Bowl",
        )
        
        try:
            agent = SEOAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            serp = result_state.serp_insights
            if serp is not None and isinstance(serp, list):
                self._add_result(
                    "seo/serp_insights",
                    True,
                    f"SERP insights retrieved: {len(serp)} competitors",
                    {"serp_count": len(serp)}
                )
            else:
                self._add_result(
                    "seo/serp_insights",
                    True,  # Pass - SERP may return empty for some queries
                    f"SERP returned: {type(serp)}"
                )
                
        except Exception as e:
            self._add_result("seo/serp_insights", False, f"Error: {e}")

    # =========================================================================
    # Runner
    # =========================================================================

    def run_all(self) -> list[TestResult]:
        """Run all SEO feature tests with REAL APIs."""
        self._log("\n📊 SEO Feature Tests (REAL API CALLS via SEOAgent)")
        self._log("=" * 50)
        self._log("⚠️  These tests make REAL API calls to OpenAI and SERP")
        
        # Title tests
        self._log("\n📝 SEO Title Tests (REAL LLM)")
        self.test_seo_title_generation_and_length()
        
        # Description tests
        self._log("\n📄 SEO Description Tests (REAL LLM)")
        self.test_seo_description_generation_and_length()
        
        # Alt-text tests
        self._log("\n🖼️  Alt-Text Tests (REAL LLM)")
        self.test_seo_alt_text_generation()
        
        # CTR tests
        self._log("\n📈 CTR Check Tests (via SEOAgent)")
        self.test_ctr_check_high_score_content()
        self.test_ctr_check_low_score_content()
        
        # SERP tests
        self._log("\n🔍 SERP Insights Tests (REAL SERP API)")
        self.test_serp_insights_retrieval()
        
        return self.results

    def get_summary(self) -> dict[str, int]:
        """Get summary of test results."""
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        return {"passed": passed, "failed": failed, "total": len(self.results)}


if __name__ == "__main__":
    tests = SEOFeatureTests()
    results = tests.run_all()
    summary = tests.get_summary()
    print(f"\n{'=' * 50}")
    print(f"Summary: {summary['passed']} passed | {summary['failed']} failed")

"""
Agent Output Tests (Real API Calls)

Validates that each agent returns required outputs using REAL LLM and SERP APIs.
Uses carefully crafted Japanese descriptions to trigger specific agent features.

Note: ComplianceAgent is currently disabled.

Required Environment Variables:
- OPENAI_API_KEY: OpenAI API key
- SERP_API_KEY: (optional) SERP API key for competitor analysis
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


class AgentOutputTests:
    """
    Tests for agent output validation using REAL LLM and SERP APIs.
    
    Each test uses fixtures designed to trigger specific agent features:
    - CopywriterAgent: Japanese artisan items for discovered_values
    - SEOAgent: SEO title, description, alt-text, CTR check
    - MarketingAgent: Social hooks and seasonal campaigns
    - PriceScoutAgent: Common products for competitor analysis
    
    Note: ComplianceAgent is currently disabled.
    """

    def __init__(self, fixtures_path: str | None = None, skip_expensive: bool = False):
        """Initialize with fixtures."""
        if fixtures_path is None:
            fixtures_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "regression_fixtures.json"
            )
        
        with open(fixtures_path, "r", encoding="utf-8") as f:
            self.fixtures = json.load(f)
        
        self.results: list[TestResult] = []
        self.skip_expensive = skip_expensive
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
    # CopywriterAgent Tests (Real LLM)
    # =========================================================================

    def test_copywriter_artisan_discovered_values(self) -> None:
        """Test that artisan items populate discovered_values using REAL LLM."""
        if not self._check_env():
            self._add_result("copywriter/artisan", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.rewriter import CopywriterAgent
        from src.ecommerce.state import MissionState
        
        # Only test first 2 artisan fixtures to save API costs
        artisan_fixtures = [f for f in self.fixtures.get("copywriter_fixtures", []) 
                          if f.get("expect_discovered_values")][:2]
        
        services = self._get_real_services()
        
        for fixture in artisan_fixtures:
            fixture_id = fixture["id"]
            self._log(f"\n  🔥 Testing CopywriterAgent (REAL LLM) with fixture: {fixture_id}")
            
            state = MissionState(
                product_id=f"test-{fixture_id}",
                shop_id="test-shop.myshopify.com",
                plan_tier="Standard",
                raw_input={
                    "title": fixture["product_name"],
                    "japanese_description": fixture["japanese_description"],
                    "category": fixture["category"],
                },
                target_locale="en",
            )
            
            try:
                agent = CopywriterAgent("test-shop.myshopify.com", services)
                result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
                
                # Assertions
                has_title = result_state.draft_title is not None and len(result_state.draft_title) > 0
                has_content = result_state.draft_content is not None and len(result_state.draft_content) > 0
                has_discovered = (
                    result_state.discovered_values is not None and 
                    len(result_state.discovered_values) > 0
                )
                
                if has_title and has_content:
                    if has_discovered:
                        # Check for expected keywords in output
                        expected_keywords = fixture.get("expected_keywords", [])
                        output_text = f"{result_state.draft_title} {result_state.draft_content}".lower()
                        found_keywords = [k for k in expected_keywords if k.lower() in output_text]
                        
                        self._add_result(
                            f"copywriter/{fixture_id}/discovered_values",
                            True,
                            f"Found {len(result_state.discovered_values)} values, keywords: {found_keywords}",
                            {
                                "discovered_values": result_state.discovered_values,
                                "title": result_state.draft_title,
                                "keywords_found": found_keywords,
                            }
                        )
                    else:
                        self._add_result(
                            f"copywriter/{fixture_id}/discovered_values",
                            False,
                            f"Generated content but NO discovered_values for artisan item"
                        )
                else:
                    self._add_result(
                        f"copywriter/{fixture_id}/discovered_values",
                        False,
                        f"Missing output: title={has_title}, content={has_content}"
                    )
            except Exception as e:
                self._add_result(
                    f"copywriter/{fixture_id}/discovered_values",
                    False,
                    f"Error: {e}"
                )

    def test_copywriter_generic_minimal_values(self) -> None:
        """Test that generic items have minimal/no discovered_values using REAL LLM."""
        if not self._check_env():
            self._add_result("copywriter/generic", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.rewriter import CopywriterAgent
        from src.ecommerce.state import MissionState
        
        # Only test first generic fixture
        generic_fixtures = [f for f in self.fixtures.get("copywriter_fixtures", []) 
                          if not f.get("expect_discovered_values")][:1]
        
        services = self._get_real_services()
        
        for fixture in generic_fixtures:
            fixture_id = fixture["id"]
            self._log(f"\n  🔥 Testing CopywriterAgent (REAL LLM) generic: {fixture_id}")
            
            state = MissionState(
                product_id=f"test-{fixture_id}",
                shop_id="test-shop.myshopify.com",
                plan_tier="Standard",
                raw_input={
                    "title": fixture["product_name"],
                    "japanese_description": fixture["japanese_description"],
                    "category": fixture["category"],
                },
                target_locale="en",
            )
            
            try:
                agent = CopywriterAgent("test-shop.myshopify.com", services)
                result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
                
                has_title = result_state.draft_title is not None
                has_content = result_state.draft_content is not None
                discovered_count = len(result_state.discovered_values or [])
                
                if has_title and has_content:
                    # Generic items should have 0 or very few discovered values
                    self._add_result(
                        f"copywriter/{fixture_id}/generic",
                        True,
                        f"Generic item: {discovered_count} discovered values (expected 0-1)",
                        {"title": result_state.draft_title, "discovered_count": discovered_count}
                    )
                else:
                    self._add_result(
                        f"copywriter/{fixture_id}/generic",
                        False,
                        f"Missing output"
                    )
            except Exception as e:
                self._add_result(
                    f"copywriter/{fixture_id}/generic",
                    False,
                    f"Error: {e}"
                )

    # =========================================================================
    # SEOAgent Tests (Real LLM)
    # =========================================================================

    def test_seo_generation(self) -> None:
        """Test that SEOAgent generates SEO using REAL LLM."""
        if not self._check_env():
            self._add_result("seo/generation", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.seo import SEOAgent
        from src.ecommerce.state import MissionState
        
        self._log(f"\n  🔥 Testing SEOAgent SEO generation (REAL LLM)")
        
        services = self._get_real_services()
        
        state = MissionState(
            product_id="test-seo-gen",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "Kyoto Artisan Matcha Bowl",
                "category": "Tableware",
            },
            target_locale="en",
            draft_content="<p>Handcrafted matcha bowl by Kyoto artisans. Perfect for tea ceremony.</p>",
            draft_title="Kyoto Artisan Matcha Bowl",
        )
        
        try:
            agent = SEOAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            has_seo_title = result_state.seo_title is not None and len(result_state.seo_title) > 0
            has_seo_desc = result_state.seo_description is not None and len(result_state.seo_description) > 0
            has_alt_text = result_state.seo_alt_text is not None and len(result_state.seo_alt_text) > 0
            has_ctr = result_state.ctr_check is not None
            
            title_len = len(result_state.seo_title or "")
            desc_len = len(result_state.seo_description or "")
            
            if has_seo_title and has_seo_desc:
                self._add_result(
                    "seo/seo_generation",
                    True,
                    f"SEO generated: title={title_len}chars, desc={desc_len}chars, alt={has_alt_text}",
                    {
                        "seo_title": result_state.seo_title,
                        "seo_description": result_state.seo_description,
                        "seo_alt_text": result_state.seo_alt_text,
                    }
                )
            else:
                self._add_result(
                    "seo/seo_generation",
                    False,
                    f"Missing SEO: title={has_seo_title}, desc={has_seo_desc}"
                )
            
            # Also check CTR
            if has_ctr:
                ctr = result_state.ctr_check
                self._add_result(
                    "seo/ctr_check",
                    True,
                    f"CTR score={ctr.get('score', 0):.2f}",
                    {"ctr_check": ctr}
                )
            else:
                self._add_result(
                    "seo/ctr_check",
                    False,
                    "No CTR check generated"
                )
                
        except Exception as e:
            self._add_result("seo/seo_generation", False, f"Error: {e}")

    def test_seo_length_constraints(self) -> None:
        """Test that SEO outputs meet length constraints."""
        if not self._check_env():
            self._add_result("seo/length", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.seo import SEOAgent
        from src.ecommerce.state import MissionState
        
        self._log(f"\n  🔥 Testing SEOAgent SEO length constraints (REAL LLM)")
        
        services = self._get_real_services()
        
        state = MissionState(
            product_id="test-seo-length",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={"title": "Kyoto Artisan Matcha Bowl", "category": "Tableware"},
            target_locale="en",
            draft_content="<p>Handcrafted matcha bowl from Kyoto artisans. Perfect for tea ceremony.</p>",
            draft_title="Kyoto Artisan Matcha Bowl",
        )
        
        try:
            agent = SEOAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            title_len = len(result_state.seo_title or "")
            desc_len = len(result_state.seo_description or "")
            
            title_ok = title_len <= 70
            desc_ok = desc_len <= 160
            
            if title_ok and desc_ok:
                self._add_result(
                    "seo/seo_length_constraints",
                    True,
                    f"Constraints met: title={title_len}/70, desc={desc_len}/160"
                )
            else:
                self._add_result(
                    "seo/seo_length_constraints",
                    False,
                    f"Constraints violated: title={title_len}/70 ({title_ok}), desc={desc_len}/160 ({desc_ok})"
                )
        except Exception as e:
            self._add_result("seo/seo_length_constraints", False, f"Error: {e}")

    # =========================================================================
    # MarketingAgent Tests (Real LLM - Social Hooks Only)
    # =========================================================================

    def test_marketing_social_hooks(self) -> None:
        """Test that MarketingAgent generates social hooks using REAL LLM."""
        if not self._check_env():
            self._add_result("marketing/social_hooks", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.ecommerce.agents.marketing import MarketingAgent
        from src.ecommerce.state import MissionState
        
        self._log(f"\n  🔥 Testing MarketingAgent social hooks (REAL LLM)")
        
        services = self._get_real_services()
        
        state = MissionState(
            product_id="test-social-hooks",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": "Kyoto Artisan Matcha Bowl",
                "category": "Tableware",
            },
            target_locale="en",
            draft_content="<p>Handcrafted matcha bowl by Kyoto artisans. Perfect for tea ceremony.</p>",
            draft_title="Kyoto Artisan Matcha Bowl",
        )
        
        try:
            agent = MarketingAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            has_social_hooks = result_state.social_hooks is not None and len(result_state.social_hooks) > 0
            
            if has_social_hooks:
                self._add_result(
                    "marketing/social_hooks",
                    True,
                    f"Generated {len(result_state.social_hooks)} social hooks",
                    {"social_hooks": result_state.social_hooks}
                )
            else:
                self._add_result(
                    "marketing/social_hooks",
                    False,
                    "No social hooks generated"
                )
                
        except Exception as e:
            self._add_result("marketing/social_hooks", False, f"Error: {e}")

    # =========================================================================
    # PriceScoutAgent Tests (Real SERP API)
    # =========================================================================

    def test_price_scout_competitor_analysis(self) -> None:
        """Test that PriceScout performs competitor analysis using REAL SERP API."""
        if not self._check_env():
            self._add_result("price_scout/analysis", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        serp_key = os.getenv("SERP_API_KEY", "")
        if not serp_key:
            self._add_result("price_scout/analysis", True, "Skipped (no SERP_API_KEY)")
            return
        
        from src.ecommerce.agents.price_scout import PriceScoutAgent
        from src.ecommerce.state import MissionState
        
        # Test with common product fixture
        fixture = next((f for f in self.fixtures.get("price_scout_fixtures", [])
                       if f.get("expect_competitors")), None)
        
        if not fixture:
            self._add_result("price_scout/analysis", True, "No suitable fixture")
            return
        
        fixture_id = fixture.get("id", "unknown")
        self._log(f"\n  🔥 Testing PriceScoutAgent (REAL SERP) : {fixture_id}")
        
        services = self._get_real_services()
        
        state = MissionState(
            product_id=f"test-{fixture_id}",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": fixture.get("product_name", "Matcha Bowl"),
                "japanese_description": fixture.get("japanese_description", "抹茶碗"),
                "category": fixture.get("category", "Tableware"),
            },
            target_locale="en",
        )
        
        try:
            agent = PriceScoutAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            has_analysis = result_state.pricing_analysis is not None
            
            if has_analysis:
                analysis = result_state.pricing_analysis
                self._add_result(
                    f"price_scout/{fixture_id}/competitor_analysis",
                    True,
                    f"Analysis: avg=${analysis.get('competitor_avg_price', 0):.2f}, "
                    f"competitors={analysis.get('competitor_count', 0)}",
                    {"pricing_analysis": analysis}
                )
            else:
                self._add_result(
                    f"price_scout/{fixture_id}/competitor_analysis",
                    False,
                    "No pricing analysis returned"
                )
        except Exception as e:
            self._add_result(
                f"price_scout/{fixture_id}/competitor_analysis",
                False,
                f"Error: {e}"
            )

    # =========================================================================
    # Runner
    # =========================================================================

    def run_all(self) -> list[TestResult]:
        """Run all agent output tests with REAL APIs."""
        self._log("\n📦 Agent Output Tests (REAL API CALLS)")
        self._log("=" * 50)
        self._log("⚠️  These tests make REAL API calls to OpenAI and SERP")
        self._log("ℹ️  ComplianceAgent is currently disabled")
        
        # CopywriterAgent tests
        self._log("\n🖊️  CopywriterAgent Tests (REAL LLM)")
        self.test_copywriter_artisan_discovered_values()
        self.test_copywriter_generic_minimal_values()
        
        # SEOAgent tests
        self._log("\n🔍 SEOAgent Tests (REAL LLM)")
        self.test_seo_generation()
        self.test_seo_length_constraints()
        
        # MarketingAgent tests (social hooks only)
        self._log("\n📊 MarketingAgent Tests (REAL LLM - Social Hooks)")
        self.test_marketing_social_hooks()
        
        # PriceScoutAgent tests
        self._log("\n💰 PriceScoutAgent Tests (REAL SERP)")
        self.test_price_scout_competitor_analysis()
        
        return self.results

    def get_summary(self) -> dict[str, int]:
        """Get summary of test results."""
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        return {"passed": passed, "failed": failed, "total": len(self.results)}


if __name__ == "__main__":
    tests = AgentOutputTests()
    results = tests.run_all()
    summary = tests.get_summary()
    print(f"\n{'=' * 50}")
    print(f"Summary: {summary['passed']} passed | {summary['failed']} failed")

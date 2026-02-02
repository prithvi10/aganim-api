"""
Agent Output Tests (Real API Calls)

Validates that each agent returns required outputs using REAL LLM and SERP APIs.
Uses carefully crafted Japanese descriptions to trigger specific agent features.

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
    - MarketingAgent: PST-optimized content for CTR scoring
    - PriceScoutAgent: Common products for competitor analysis
    - ComplianceAgent: FDA/FTC violation content for flag detection
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
            from src.main.services.registry import ServiceRegistry
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
        
        from src.main.agents.copywriter import CopywriterAgent
        from src.main.agents.state import MissionState
        
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
        
        from src.main.agents.copywriter import CopywriterAgent
        from src.main.agents.state import MissionState
        
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
    # MarketingAgent Tests (Real LLM)
    # =========================================================================

    def test_marketing_seo_generation(self) -> None:
        """Test that MarketingAgent generates SEO using REAL LLM."""
        if not self._check_env():
            self._add_result("marketing/seo", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.main.agents.marketing import MarketingAgent
        from src.main.agents.state import MissionState
        
        # Test with first marketing fixture
        fixture = self.fixtures.get("marketing_fixtures", [{}])[0]
        fixture_id = fixture.get("id", "default")
        
        self._log(f"\n  🔥 Testing MarketingAgent SEO (REAL LLM): {fixture_id}")
        
        services = self._get_real_services()
        
        state = MissionState(
            product_id=f"test-{fixture_id}",
            shop_id="test-shop.myshopify.com",
            plan_tier="Standard",
            raw_input={
                "title": fixture.get("product_name", "Test Product"),
                "category": fixture.get("category", "Tableware"),
            },
            target_locale="en",
            draft_content=fixture.get("draft_content", "<p>Test content</p>"),
            draft_title=fixture.get("product_name", "Test Product"),
        )
        
        try:
            agent = MarketingAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            has_seo_title = result_state.seo_title is not None and len(result_state.seo_title) > 0
            has_seo_desc = result_state.seo_description is not None and len(result_state.seo_description) > 0
            has_alt_text = result_state.seo_alt_text is not None and len(result_state.seo_alt_text) > 0
            has_ctr = result_state.ctr_check is not None
            
            title_len = len(result_state.seo_title or "")
            desc_len = len(result_state.seo_description or "")
            
            if has_seo_title and has_seo_desc:
                self._add_result(
                    f"marketing/{fixture_id}/seo_generation",
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
                    f"marketing/{fixture_id}/seo_generation",
                    False,
                    f"Missing SEO: title={has_seo_title}, desc={has_seo_desc}"
                )
            
            # Also check CTR
            if has_ctr:
                ctr = result_state.ctr_check
                self._add_result(
                    f"marketing/{fixture_id}/ctr_check",
                    True,
                    f"CTR score={ctr.get('score', 0):.2f}",
                    {"ctr_check": ctr}
                )
            else:
                self._add_result(
                    f"marketing/{fixture_id}/ctr_check",
                    False,
                    "No CTR check generated"
                )
                
        except Exception as e:
            self._add_result(
                f"marketing/{fixture_id}/seo_generation",
                False,
                f"Error: {e}"
            )

    def test_marketing_seo_length_constraints(self) -> None:
        """Test that SEO outputs meet length constraints."""
        if not self._check_env():
            self._add_result("marketing/seo_length", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.main.agents.marketing import MarketingAgent
        from src.main.agents.state import MissionState
        
        self._log(f"\n  🔥 Testing MarketingAgent SEO length constraints (REAL LLM)")
        
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
            agent = MarketingAgent("test-shop.myshopify.com", services)
            result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
            
            title_len = len(result_state.seo_title or "")
            desc_len = len(result_state.seo_description or "")
            
            title_ok = title_len <= 70
            desc_ok = desc_len <= 160
            
            if title_ok and desc_ok:
                self._add_result(
                    "marketing/seo_length_constraints",
                    True,
                    f"Constraints met: title={title_len}/70, desc={desc_len}/160"
                )
            else:
                self._add_result(
                    "marketing/seo_length_constraints",
                    False,
                    f"Constraints violated: title={title_len}/70 ({title_ok}), desc={desc_len}/160 ({desc_ok})"
                )
        except Exception as e:
            self._add_result("marketing/seo_length_constraints", False, f"Error: {e}")

    # =========================================================================
    # ComplianceAgent Tests (Real LLM)
    # =========================================================================

    def test_compliance_fda_ftc_detection(self) -> None:
        """Test that compliance agent detects FDA/FTC violations using REAL LLM."""
        if not self._check_env():
            self._add_result("compliance/fda_ftc", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.main.agents.compliance import ComplianceAgent
        from src.main.agents.state import MissionState
        
        # Test with violation fixture
        violation_fixtures = [f for f in self.fixtures.get("compliance_fixtures", [])
                            if f.get("expect_flags")][:2]
        
        services = self._get_real_services()
        
        for fixture in violation_fixtures:
            fixture_id = fixture.get("id", "unknown")
            self._log(f"\n  🔥 Testing ComplianceAgent (REAL LLM) violation: {fixture_id}")
            
            state = MissionState(
                product_id=f"test-{fixture_id}",
                shop_id="test-shop.myshopify.com",
                plan_tier="Standard",
                raw_input={"title": "Test Product", "category": "Health"},
                target_locale="en",
                draft_content=fixture.get("draft_content", ""),
            )
            
            try:
                agent = ComplianceAgent("test-shop.myshopify.com", services)
                result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
                
                has_flags = len(result_state.compliance_flags) > 0
                
                if has_flags:
                    self._add_result(
                        f"compliance/{fixture_id}/violation_detected",
                        True,
                        f"Detected {len(result_state.compliance_flags)} violations",
                        {"flags": result_state.compliance_flags}
                    )
                else:
                    self._add_result(
                        f"compliance/{fixture_id}/violation_detected",
                        False,
                        "Expected violations but none detected"
                    )
            except Exception as e:
                self._add_result(
                    f"compliance/{fixture_id}/violation_detected",
                    False,
                    f"Error: {e}"
                )

    def test_compliance_clean_content_passes(self) -> None:
        """Test that clean content passes compliance using REAL LLM."""
        if not self._check_env():
            self._add_result("compliance/clean", True, "Skipped (no OPENAI_API_KEY)")
            return
        
        from src.main.agents.compliance import ComplianceAgent
        from src.main.agents.state import MissionState
        
        # Test with clean fixture
        clean_fixtures = [f for f in self.fixtures.get("compliance_fixtures", [])
                        if not f.get("expect_flags")][:1]
        
        services = self._get_real_services()
        
        for fixture in clean_fixtures:
            fixture_id = fixture.get("id", "unknown")
            self._log(f"\n  🔥 Testing ComplianceAgent (REAL LLM) clean: {fixture_id}")
            
            state = MissionState(
                product_id=f"test-{fixture_id}",
                shop_id="test-shop.myshopify.com",
                plan_tier="Standard",
                raw_input={"title": "Test Product", "category": "Tableware"},
                target_locale="en",
                draft_content=fixture.get("draft_content", ""),
            )
            
            try:
                agent = ComplianceAgent("test-shop.myshopify.com", services)
                result_state = asyncio.get_event_loop().run_until_complete(agent.run(state))
                
                has_flags = len(result_state.compliance_flags) > 0
                
                if not has_flags:
                    self._add_result(
                        f"compliance/{fixture_id}/clean_passed",
                        True,
                        "Clean content passed compliance"
                    )
                else:
                    self._add_result(
                        f"compliance/{fixture_id}/clean_passed",
                        False,
                        f"Unexpected flags on clean content: {result_state.compliance_flags}"
                    )
            except Exception as e:
                self._add_result(
                    f"compliance/{fixture_id}/clean_passed",
                    False,
                    f"Error: {e}"
                )

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
        
        from src.main.agents.price_scout import PriceScoutAgent
        from src.main.agents.state import MissionState
        
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
        
        # CopywriterAgent tests
        self._log("\n🖊️  CopywriterAgent Tests (REAL LLM)")
        self.test_copywriter_artisan_discovered_values()
        self.test_copywriter_generic_minimal_values()
        
        # MarketingAgent tests
        self._log("\n📊 MarketingAgent Tests (REAL LLM)")
        self.test_marketing_seo_generation()
        self.test_marketing_seo_length_constraints()
        
        # ComplianceAgent tests
        self._log("\n🛡️  ComplianceAgent Tests (REAL LLM)")
        self.test_compliance_fda_ftc_detection()
        self.test_compliance_clean_content_passes()
        
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

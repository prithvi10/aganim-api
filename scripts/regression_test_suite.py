#!/usr/bin/env python3
"""
Local Regression Test Suite (REAL API CALLS)

Pre-commit regression suite that validates all agents using REAL LLM and SERP APIs.
Run this before every commit push to ensure the agent pipeline works correctly.

Usage:
    # Run all tests (requires OPENAI_API_KEY)
    python scripts/regression_test_suite.py
    
    # Run specific module
    python scripts/regression_test_suite.py --module agents
    python scripts/regression_test_suite.py --module seo
    python scripts/regression_test_suite.py --module tables
    python scripts/regression_test_suite.py --module rag
    python scripts/regression_test_suite.py --module tiers
    
    # Run multiple modules
    python scripts/regression_test_suite.py --module agents --module seo
    
    # Generate reports
    python scripts/regression_test_suite.py --report-json logs/report.json --report-md logs/report.md

Required Environment Variables:
- OPENAI_API_KEY: OpenAI API key (required)
- SERP_API_KEY: SERP API key (optional, for competitor analysis)

Note: This suite makes REAL API calls which cost money. Use judiciously.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# Ensure repo root is on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _log(msg: str) -> None:
    """Log a message to stdout."""
    print(msg)


def _check_environment() -> dict[str, bool]:
    """Check required environment variables."""
    return {
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY", "")),
        "SERP_API_KEY": bool(os.getenv("SERP_API_KEY", "")),
    }


def _run_agent_tests() -> dict[str, Any]:
    """Run agent output tests."""
    from scripts.tests.agent_output_tests import AgentOutputTests
    
    tests = AgentOutputTests()
    results = tests.run_all()
    summary = tests.get_summary()
    
    return {
        "module": "agents",
        "results": [
            {"name": r.name, "passed": r.passed, "message": r.message, "details": r.details}
            for r in results
        ],
        "summary": summary,
    }


def _run_seo_tests() -> dict[str, Any]:
    """Run SEO feature tests."""
    from scripts.tests.seo_feature_tests import SEOFeatureTests
    
    tests = SEOFeatureTests()
    results = tests.run_all()
    summary = tests.get_summary()
    
    return {
        "module": "seo",
        "results": [
            {"name": r.name, "passed": r.passed, "message": r.message, "details": r.details}
            for r in results
        ],
        "summary": summary,
    }


def _run_table_tests() -> dict[str, Any]:
    """Run spec table tests."""
    from scripts.tests.spec_table_tests import SpecTableTests
    
    tests = SpecTableTests()
    results = tests.run_all()
    summary = tests.get_summary()
    
    return {
        "module": "tables",
        "results": [
            {"name": r.name, "passed": r.passed, "message": r.message, "details": r.details}
            for r in results
        ],
        "summary": summary,
    }


def _run_rag_tests() -> dict[str, Any]:
    """Run RAG brand soul tests."""
    from scripts.tests.rag_brand_soul_tests import RAGBrandSoulTests
    
    tests = RAGBrandSoulTests()
    results = tests.run_all()
    summary = tests.get_summary()
    
    return {
        "module": "rag",
        "results": [
            {"name": r.name, "passed": r.passed, "message": r.message, "details": r.details}
            for r in results
        ],
        "summary": summary,
    }


def _run_tier_tests() -> dict[str, Any]:
    """Run tier feature tests."""
    from scripts.tests.tier_feature_tests import TierFeatureTests
    
    tests = TierFeatureTests()
    results = tests.run_all()
    summary = tests.get_summary()
    
    return {
        "module": "tiers",
        "results": [
            {"name": r.name, "passed": r.passed, "message": r.message, "details": r.details}
            for r in results
        ],
        "summary": summary,
    }


def _run_ingest_tests() -> dict[str, Any]:
    """Run brand soul ingestion tests."""
    from scripts.tests.brand_ingest_tests import BrandIngestTests

    tests = BrandIngestTests()
    results = tests.run_all()
    summary = tests.get_summary()

    return {
        "module": "ingest",
        "results": [
            {"name": r.name, "passed": r.passed, "message": r.message, "details": r.details}
            for r in results
        ],
        "summary": summary,
    }


# Module runner mapping
MODULE_RUNNERS = {
    "agents": _run_agent_tests,
    "seo": _run_seo_tests,
    "tables": _run_table_tests,
    "rag": _run_rag_tests,
    "tiers": _run_tier_tests,
    "ingest": _run_ingest_tests,
}


def _generate_markdown_report(all_results: list[dict], duration: float) -> str:
    """Generate a markdown report."""
    lines = [
        "# Regression Test Report",
        "",
        f"**Date:** {datetime.now(timezone.utc).isoformat()}",
        f"**Duration:** {duration:.2f}s",
        "",
        "## Summary",
        "",
        "| Module | Passed | Failed | Total |",
        "|--------|--------|--------|-------|",
    ]
    
    total_passed = 0
    total_failed = 0
    
    for result in all_results:
        module = result["module"]
        summary = result["summary"]
        passed = summary["passed"]
        failed = summary["failed"]
        total = summary["total"]
        total_passed += passed
        total_failed += failed
        
        status_emoji = "✅" if failed == 0 else "❌"
        lines.append(f"| {status_emoji} {module} | {passed} | {failed} | {total} |")
    
    lines.append(f"| **Total** | **{total_passed}** | **{total_failed}** | **{total_passed + total_failed}** |")
    lines.append("")
    
    # Failed tests detail
    failed_tests = []
    for result in all_results:
        for test in result["results"]:
            if not test["passed"]:
                failed_tests.append(test)
    
    if failed_tests:
        lines.append("## Failed Tests")
        lines.append("")
        for test in failed_tests:
            lines.append(f"### ❌ {test['name']}")
            lines.append(f"**Message:** {test['message']}")
            if test.get("details"):
                lines.append(f"**Details:** `{json.dumps(test['details'])[:200]}...`")
            lines.append("")
    
    return "\n".join(lines)


def _generate_json_report(all_results: list[dict], duration: float) -> dict:
    """Generate a JSON report."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration,
        "modules": all_results,
        "summary": {
            "total_passed": sum(r["summary"]["passed"] for r in all_results),
            "total_failed": sum(r["summary"]["failed"] for r in all_results),
            "total_tests": sum(r["summary"]["total"] for r in all_results),
        },
    }


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Local Regression Test Suite (REAL API CALLS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--module",
        action="append",
        choices=list(MODULE_RUNNERS.keys()),
        help="Run specific test modules (can be repeated). Default: all",
    )
    parser.add_argument(
        "--report-json",
        type=str,
        default="",
        help="Path to write JSON report",
    )
    parser.add_argument(
        "--report-md",
        type=str,
        default="",
        help="Path to write Markdown report",
    )
    parser.add_argument(
        "--skip-cost-warning",
        action="store_true",
        help="Skip the API cost warning prompt",
    )
    
    args = parser.parse_args()
    
    # Check environment
    env_status = _check_environment()
    
    _log("")
    _log("=" * 60)
    _log("  🚦 LOCAL REGRESSION TEST SUITE (REAL API CALLS)")
    _log("=" * 60)
    _log(f"  📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _log(f"  🔑 OPENAI_API_KEY: {'✅ Set' if env_status['OPENAI_API_KEY'] else '❌ Missing'}")
    _log(f"  🔍 SERP_API_KEY: {'✅ Set' if env_status['SERP_API_KEY'] else '⚠️  Optional'}")
    _log("")
    
    if not env_status["OPENAI_API_KEY"]:
        _log("❌ ERROR: OPENAI_API_KEY is required for real API tests")
        _log("   Set it with: export OPENAI_API_KEY='sk-...'")
        return 1
    
    # Cost warning
    if not args.skip_cost_warning:
        _log("⚠️  WARNING: This suite makes REAL API calls to OpenAI.")
        _log("   Estimated cost: $0.05 - $0.20 depending on modules.")
        _log("   Use --skip-cost-warning to skip this prompt.")
        _log("")
        try:
            response = input("   Continue? [y/N]: ").strip().lower()
            if response != "y":
                _log("   Aborted.")
                return 0
        except (EOFError, KeyboardInterrupt):
            _log("\n   Aborted.")
            return 0
    
    # Determine modules to run
    modules_to_run = args.module if args.module else list(MODULE_RUNNERS.keys())
    
    _log("")
    _log(f"  📦 Modules: {', '.join(modules_to_run)}")
    _log("")
    
    start_time = time.time()
    all_results = []
    
    for module in modules_to_run:
        if module not in MODULE_RUNNERS:
            _log(f"❌ Unknown module: {module}")
            continue
        
        try:
            result = MODULE_RUNNERS[module]()
            all_results.append(result)
        except Exception as e:
            _log(f"❌ Error running {module}: {e}")
            all_results.append({
                "module": module,
                "results": [{"name": f"{module}/error", "passed": False, "message": str(e), "details": None}],
                "summary": {"passed": 0, "failed": 1, "total": 1},
            })
    
    duration = time.time() - start_time
    
    # Print summary
    _log("")
    _log("=" * 60)
    _log("  📊 FINAL SUMMARY")
    _log("=" * 60)
    
    total_passed = 0
    total_failed = 0
    
    for result in all_results:
        module = result["module"]
        summary = result["summary"]
        passed = summary["passed"]
        failed = summary["failed"]
        total_passed += passed
        total_failed += failed
        
        status = "✅" if failed == 0 else "❌"
        _log(f"  {status} {module}: {passed}/{passed + failed} passed")
    
    _log("")
    _log(f"  Total: {total_passed} passed | {total_failed} failed")
    _log(f"  Duration: {duration:.2f}s")
    _log("")
    
    # Generate reports
    if args.report_json:
        report_dir = os.path.dirname(args.report_json)
        if report_dir:
            os.makedirs(report_dir, exist_ok=True)
        with open(args.report_json, "w", encoding="utf-8") as f:
            json.dump(_generate_json_report(all_results, duration), f, indent=2)
        _log(f"  📄 JSON report: {args.report_json}")
    
    if args.report_md:
        report_dir = os.path.dirname(args.report_md)
        if report_dir:
            os.makedirs(report_dir, exist_ok=True)
        with open(args.report_md, "w", encoding="utf-8") as f:
            f.write(_generate_markdown_report(all_results, duration))
        _log(f"  📄 Markdown report: {args.report_md}")
    
    # Final result
    if total_failed > 0:
        _log("")
        _log("  ❌ SOME TESTS FAILED")
        _log("")
        _log("  Failed tests:")
        for result in all_results:
            for test in result["results"]:
                if not test["passed"]:
                    _log(f"    - {test['name']}: {test['message']}")
        return 1
    else:
        _log("")
        _log("  ✅ ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())

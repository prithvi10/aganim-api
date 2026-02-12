"""
Full Local RAG Test Suite — Orchestrator

Runs all local RAG test suites sequentially:
  1. Onboarding → Ingestion (original RAG tests)
  2. Strategic Intelligence Extraction
  3. Template Content Generation (product + marketing)
  4. Writing Studio Full E2E

Usage:
  python -m scripts.rag.local_rag_full_test
  python -m scripts.rag.local_rag_full_test --include-templates   # also run template tests
  python -m scripts.rag.local_rag_full_test --all                 # run everything
"""

import argparse
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rag import onboarding_to_ingestion_local


def _run_suite(name: str, fn: Callable[[], None]) -> bool:
    """Run a test suite and return True if passed."""
    print(f"\n{'#' * 70}")
    print(f"# {name}")
    print(f"{'#' * 70}")
    try:
        fn()
        return True
    except SystemExit as exc:
        if exc.code and exc.code != 0:
            print(f"❌ {name} failed (exit code {exc.code})")
            return False
        return True
    except Exception as exc:
        print(f"❌ {name} error: {exc}")
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Full Local RAG Test Suite")
    ap.add_argument("--include-templates", action="store_true", help="Include template generation tests")
    ap.add_argument("--include-intelligence", action="store_true", help="Include intelligence extraction tests")
    ap.add_argument("--all", action="store_true", help="Run all test suites")
    args = ap.parse_args()

    suites: list[tuple[str, Callable[[], None]]] = [
        ("RAG: Onboarding → Ingestion", onboarding_to_ingestion_local.main),
    ]

    if args.include_intelligence or args.all:
        from scripts.rag import local_intelligence_test
        suites.append(("Intelligence: Strategic Extraction", local_intelligence_test.main))

    if args.include_templates or args.all:
        from scripts.rag import local_template_test
        suites.append(("Templates: Content Generation", local_template_test.main))

    if args.all:
        from scripts.rag import local_writing_studio_full_test
        suites.append(("Writing Studio: Full E2E", local_writing_studio_full_test.main))

    passed = 0
    failed = 0
    for name, fn in suites:
        ok = _run_suite(name, fn)
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n{'=' * 70}")
    print(f"🚦 Full RAG Suite: ✅ {passed} passed | ❌ {failed} failed")
    print(f"{'=' * 70}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

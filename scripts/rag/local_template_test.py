"""
Template Content Generation — Local E2E Test

Validates all content templates end-to-end with real OpenAI calls:
  1. Ingest brand soul (auto-triggers intelligence extraction)
  2. List templates via GET /api/templates
  3. Generate content for each PRODUCT template via POST /api/generate/{template_id}
  4. Generate content for each MARKETING template
  5. Validate outputs have expected JSON keys
  6. Optionally validate brand keywords in output

Prereqs:
  - Local server running (default http://localhost:8000)
  - OPENAI_API_KEY set
  - PostgreSQL running with shopify_translator DB
  - SHOPIFY_API_KEY / SHOPIFY_API_SECRET set for dev auth bypass

Usage:
  python -m scripts.rag.local_template_test
  python -m scripts.rag.local_template_test --template product/blog-post    # single template
  python -m scripts.rag.local_template_test --category product          # product templates only
  python -m scripts.rag.local_template_test --category marketing        # marketing templates only
  python -m scripts.rag.local_template_test --skip-ingest               # skip brand soul ingest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ecommerce.db.models import Shop, StoreContext, Plan, User

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shopify_translator")
CASES_PATH = os.getenv("TEMPLATE_CASES_PATH", "scripts/rag/local_template_cases.json")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def _log(msg: str) -> None:
    print(msg)


def _auth_headers(shop_domain: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer dev-token:{shop_domain}",
        "Content-Type": "application/json",
    }


def _get_db():
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, SessionLocal


def _ensure_plan_user_shop(session_factory, shop_domain: str) -> None:
    db = session_factory()
    now = datetime.now(timezone.utc)
    try:
        plan = db.query(Plan).filter(Plan.name == "Pro").first()
        if not plan:
            plan = Plan(
                name="Pro",
                monthly_rewrite_limit=10000,
                max_request_rate=500,
                product_limit=10000,
                max_locales=10,
                billing_cycle_type="recurring",
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)

        user = db.query(User).filter(User.username == shop_domain).first()
        if not user:
            user = User(username=shop_domain, email=None, plan_id=plan.id)
            db.add(user)
            db.commit()

        shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        if not shop:
            shop = Shop(
                domain=shop_domain,
                access_token="",
                current_plan_name="Pro",
                last_plan_name="Pro",
                access_expires_at=now + timedelta(days=30),
                reset_anchor_date=now,
                next_reset_date=now + timedelta(days=30),
            )
            db.add(shop)
            db.commit()
        else:
            # Ensure Pro plan for all templates
            shop.current_plan_name = "Pro"
            db.commit()
    finally:
        db.close()


def _poll_brand_context_ready(client: httpx.Client, shop: str, headers: dict, timeout_s: int = 120) -> None:
    start = time.time()
    while True:
        r = client.get(f"/api/admin/brand-context/status?shop={shop}", headers=headers)
        if r.status_code != 200:
            _fail(f"Status poll failed: {r.status_code} {r.text}")
        data = r.json()
        status = str(data.get("status") or "idle")
        if status == "ready":
            return
        if status == "failed":
            _fail(f"Ingestion failed: {data.get('last_error')}")
        if time.time() - start > timeout_s:
            _fail(f"Timed out waiting for ingestion (status={status})")
        time.sleep(2)


def _ensure_env() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        _fail("OPENAI_API_KEY is not set")


def _load_cases(path: str) -> dict:
    if not os.path.exists(path):
        _fail(f"Cases file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════
# Phase 0: Brand Soul Ingestion
# ═══════════════════════════════════════════════════════════════════════

def ingest_brand_soul(config: dict) -> str:
    """Ingest brand soul and return shop_domain."""
    bs = config["brand_soul"]
    shop_domain = bs["shop_domain"]
    headers = _auth_headers(shop_domain)

    _, SessionLocal = _get_db()
    _ensure_plan_user_shop(SessionLocal, shop_domain)

    _log("\n" + "=" * 60)
    _log("📥 Phase 0: Ingest Brand Soul")
    _log("=" * 60)

    with httpx.Client(base_url=API_BASE, timeout=180.0) as client:
        _log(f"🚀 Ingesting brand soul for {shop_domain}")
        resp = client.post(
            "/api/onboarding/brand-soul",
            json={
                "brand_persona": bs["brand_persona"],
                "core_pillars": bs.get("core_pillars", []),
                "raw_text": bs["raw_text"],
            },
            headers=headers,
        )
        if resp.status_code != 200:
            _fail(f"POST /api/onboarding/brand-soul failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if data.get("status") != "accepted":
            _fail(f"Unexpected response: {data}")
        _log("✅ Ingestion accepted")

        _log("⏳ Polling until ready...")
        _poll_brand_context_ready(client, shop_domain, headers, timeout_s=180)
        _log("✅ Brand soul ingested + intelligence extracted")

    return shop_domain


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: List Templates
# ═══════════════════════════════════════════════════════════════════════

def test_list_templates(shop_domain: str) -> list[dict]:
    """List templates via API and return the list."""
    _log("\n" + "=" * 60)
    _log("📋 Phase 1: List Templates (GET /api/templates)")
    _log("=" * 60)

    headers = _auth_headers(shop_domain)

    with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
        resp = client.get("/api/templates", headers=headers)
        if resp.status_code != 200:
            _fail(f"GET /api/templates failed: {resp.status_code} {resp.text}")

        data = resp.json()
        templates = data.get("templates", [])
        _log(f"✅ Found {len(templates)} templates")

        for t in templates:
            _log(f"   [{t['category']}] {t['id']} — {t['name']}")

    return templates


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: Generate Content per Template
# ═══════════════════════════════════════════════════════════════════════

def test_generate_template(
    client: httpx.Client,
    shop_domain: str,
    template_id: str,
    inputs: dict,
    expected_keys: list[str],
    expected_keywords: list[str],
) -> dict:
    """Generate content using a single template and validate output."""
    headers = _auth_headers(shop_domain)

    _log(f"\n   🚀 POST /api/generate/{template_id}")
    _log(f"      Inputs: {json.dumps(inputs, ensure_ascii=False)[:200]}")

    resp = client.post(
        f"/api/generate/{template_id}?shop={shop_domain}",
        json=inputs,
        headers=headers,
    )

    if resp.status_code != 200:
        _log(f"      ❌ Failed: {resp.status_code} {resp.text[:300]}")
        return {"template_id": template_id, "passed": False, "error": resp.text[:300]}

    data = resp.json()
    status = data.get("status")
    if status != "success":
        _log(f"      ❌ Unexpected status: {status}")
        return {"template_id": template_id, "passed": False, "error": f"status={status}"}

    content = data.get("content", "") or data.get("description", "")
    title_out = data.get("title", "")

    _log(f"      ✅ Generated ({len(str(content))} chars)")

    # Try parsing content as JSON for structured templates
    parsed = None
    if content:
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
        except (json.JSONDecodeError, TypeError):
            pass

    # Validate expected keys if content is JSON
    missing_keys = []
    if parsed and isinstance(parsed, dict) and expected_keys:
        for key in expected_keys:
            if key not in parsed:
                missing_keys.append(key)
        if missing_keys:
            _log(f"      ⚠️  Missing expected keys: {missing_keys}")
        else:
            _log(f"      ✅ All expected keys present: {expected_keys}")

    # Show output preview
    if parsed and isinstance(parsed, dict):
        for k, v in parsed.items():
            val_str = str(v)[:120]
            _log(f"      📝 {k}: {val_str}")
    elif content:
        _log(f"      📝 Content: {str(content)[:200]}...")

    # Keyword check
    found_kw = []
    if expected_keywords:
        haystack = str(content).lower() + " " + str(title_out).lower()
        found_kw = [kw for kw in expected_keywords if kw.lower() in haystack]
        _log(f"      🔎 Keywords: found={found_kw} expected={expected_keywords}")

    return {
        "template_id": template_id,
        "passed": True,
        "missing_keys": missing_keys,
        "content_length": len(str(content)),
        "found_keywords": found_kw,
    }


def run_template_tests(
    config: dict,
    shop_domain: str,
    filter_category: str | None = None,
    filter_template: str | None = None,
) -> list[dict]:
    """Run template generation tests."""
    results = []
    headers = _auth_headers(shop_domain)

    with httpx.Client(base_url=API_BASE, timeout=180.0) as client:
        # Product templates
        if filter_category in (None, "product"):
            product_cases = config.get("product_templates", {})
            if product_cases:
                _log("\n" + "=" * 60)
                _log("🛍️  Phase 2A: Product Templates")
                _log("=" * 60)

                for tid, case in product_cases.items():
                    if filter_template and tid != filter_template:
                        continue
                    result = test_generate_template(
                        client=client,
                        shop_domain=shop_domain,
                        template_id=tid,
                        inputs=case["inputs"],
                        expected_keys=case.get("expected_keys", []),
                        expected_keywords=case.get("expected_keywords", []),
                    )
                    results.append(result)

        # Marketing templates
        if filter_category in (None, "marketing"):
            marketing_cases = config.get("marketing_templates", {})
            if marketing_cases:
                _log("\n" + "=" * 60)
                _log("📣 Phase 2B: Marketing Templates")
                _log("=" * 60)

                for tid, case in marketing_cases.items():
                    if filter_template and tid != filter_template:
                        continue
                    result = test_generate_template(
                        client=client,
                        shop_domain=shop_domain,
                        template_id=tid,
                        inputs=case["inputs"],
                        expected_keys=case.get("expected_keys", []),
                        expected_keywords=case.get("expected_keywords", []),
                    )
                    results.append(result)

    return results


# ═══════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════

def print_summary(results: list[dict]) -> int:
    _log("\n" + "=" * 60)
    _log("📊 TEMPLATE TEST SUMMARY")
    _log("=" * 60)

    passed = 0
    failed = 0
    for r in results:
        status = "✅" if r["passed"] else "❌"
        _log(f"  {status} {r['template_id']}")
        if r.get("error"):
            _log(f"     Error: {r['error']}")
        if r.get("missing_keys"):
            _log(f"     Missing keys: {r['missing_keys']}")
        if r["passed"]:
            passed += 1
        else:
            failed += 1

    _log(f"\n  Total: {len(results)} | ✅ Passed: {passed} | ❌ Failed: {failed}")
    return failed


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    global API_BASE

    ap = argparse.ArgumentParser(
        description="Template Content Generation — Local E2E Test (real OpenAI)"
    )
    ap.add_argument("--api-base", default=os.getenv("API_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--cases", default=CASES_PATH, help="Path to template test cases JSON")
    ap.add_argument("--template", default=None, help="Run single template (e.g. product/blog-post)")
    ap.add_argument("--category", default=None, choices=["product", "marketing"], help="Filter by category")
    ap.add_argument("--skip-ingest", action="store_true", help="Skip brand soul ingestion")
    args = ap.parse_args()

    API_BASE = args.api_base

    _log("🚦 Template Content Generation — Local E2E Test Suite")
    _log(f"   API: {API_BASE}")
    _log(f"   Cases: {args.cases}")
    _ensure_env()

    config = _load_cases(args.cases)
    shop_domain = config["brand_soul"]["shop_domain"]

    # Phase 0: Ingest
    if not args.skip_ingest:
        shop_domain = ingest_brand_soul(config)
    else:
        _log("\n⏭️  Skipping brand soul ingestion (--skip-ingest)")
        _, SessionLocal = _get_db()
        _ensure_plan_user_shop(SessionLocal, shop_domain)

    # Phase 1: List templates
    test_list_templates(shop_domain)

    # Phase 2: Generate content
    results = run_template_tests(
        config=config,
        shop_domain=shop_domain,
        filter_category=args.category,
        filter_template=args.template,
    )

    # Summary
    failures = print_summary(results)
    if failures:
        sys.exit(1)

    _log("\n✅ ALL TEMPLATE TESTS PASSED")


if __name__ == "__main__":
    main()

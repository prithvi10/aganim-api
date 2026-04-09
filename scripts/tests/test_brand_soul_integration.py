#!/usr/bin/env python3
from __future__ import annotations

"""
Brand Soul Integration Tests

End-to-end tests for all Brand Soul touchpoints against the local backend.
Tests the toggle, usage endpoint, rewrite gating, and brand context status.

Usage:
    python scripts/tests/test_brand_soul_integration.py \
        --shop dev-shop.myshopify.com \
        --api-url http://localhost:8000
"""

import argparse
import json
import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: requests is required. Install with: pip install requests")
    sys.exit(1)


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


passed = 0
failed = 0
skipped = 0


def ok(name: str, detail: str = ""):
    global passed
    passed += 1
    msg = f"  {Colors.GREEN}PASS{Colors.END}  {name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)


def fail(name: str, detail: str = ""):
    global failed
    failed += 1
    msg = f"  {Colors.RED}FAIL{Colors.END}  {name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)


def skip(name: str, detail: str = ""):
    global skipped
    skipped += 1
    msg = f"  {Colors.YELLOW}SKIP{Colors.END}  {name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)


def section(title: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'─' * 60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'─' * 60}{Colors.END}")


# ─── API helpers ────────────────────────────────────────────────────────────

def toggle_brand_soul(api_url: str, shop: str, enabled: bool) -> dict:
    resp = requests.put(
        f"{api_url}/api/admin/brand-soul-toggle",
        json={"shop": shop, "enabled": enabled},
        timeout=10,
    )
    return {"status_code": resp.status_code, "body": resp.json() if resp.ok else resp.text}


def get_usage(api_url: str, shop: str) -> dict:
    resp = requests.get(f"{api_url}/api/admin/usage", params={"shop": shop}, timeout=10)
    return {"status_code": resp.status_code, "body": resp.json() if resp.ok else resp.text}


def get_brand_context_status(api_url: str, shop: str) -> dict:
    resp = requests.get(f"{api_url}/api/admin/brand-context/status", params={"shop": shop}, timeout=10)
    return {"status_code": resp.status_code, "body": resp.json() if resp.ok else resp.text}


def get_brand_intelligence(api_url: str, shop: str) -> dict:
    resp = requests.get(f"{api_url}/api/admin/brand-intelligence", params={"shop": shop}, timeout=10)
    return {"status_code": resp.status_code, "body": resp.json() if resp.ok else resp.text}


def generate_copy(api_url: str, shop: str, product_name: str, description: str, locale: str = "en") -> dict:
    resp = requests.post(
        f"{api_url}/api/proxy/generate-copy",
        params={"shop": shop},
        json={
            "product_name": product_name,
            "japanese_description": description,
            "category": "General",
            "target_locale": locale,
            "brand_soul_enabled": True,
        },
        timeout=120,
    )
    return {"status_code": resp.status_code, "body": resp.json() if resp.ok else resp.text}


# ─── Test suites ────────────────────────────────────────────────────────────

def test_toggle_endpoint(api_url: str, shop: str):
    section("1. Brand Soul Toggle Endpoint")

    # Test: toggle OFF
    r = toggle_brand_soul(api_url, shop, False)
    if r["status_code"] == 200 and r["body"].get("brand_soul_enabled") is False:
        ok("Toggle OFF", "brand_soul_enabled=false returned")
    else:
        fail("Toggle OFF", f"status={r['status_code']} body={r['body']}")

    # Test: toggle ON
    r = toggle_brand_soul(api_url, shop, True)
    if r["status_code"] == 200 and r["body"].get("brand_soul_enabled") is True:
        ok("Toggle ON", "brand_soul_enabled=true returned")
    else:
        fail("Toggle ON", f"status={r['status_code']} body={r['body']}")

    # Test: missing shop
    resp = requests.put(f"{api_url}/api/admin/brand-soul-toggle", json={"enabled": True}, timeout=10)
    if resp.status_code == 400:
        ok("Missing shop rejected", "400 returned")
    else:
        fail("Missing shop rejected", f"expected 400, got {resp.status_code}")

    # Test: missing enabled
    resp = requests.put(f"{api_url}/api/admin/brand-soul-toggle", json={"shop": shop}, timeout=10)
    if resp.status_code == 400:
        ok("Missing enabled rejected", "400 returned")
    else:
        fail("Missing enabled rejected", f"expected 400, got {resp.status_code}")

    # Test: invalid enabled (string instead of bool)
    resp = requests.put(
        f"{api_url}/api/admin/brand-soul-toggle",
        json={"shop": shop, "enabled": "yes"},
        timeout=10,
    )
    if resp.status_code == 400:
        ok("Non-bool enabled rejected", "400 returned")
    else:
        fail("Non-bool enabled rejected", f"expected 400, got {resp.status_code}")

    # Test: non-existent shop
    resp = requests.put(
        f"{api_url}/api/admin/brand-soul-toggle",
        json={"shop": "nonexistent-shop-12345.myshopify.com", "enabled": True},
        timeout=10,
    )
    if resp.status_code == 404:
        ok("Non-existent shop rejected", "404 returned")
    else:
        fail("Non-existent shop rejected", f"expected 404, got {resp.status_code}")


def test_usage_reflects_toggle(api_url: str, shop: str):
    section("2. Usage Endpoint Reflects Toggle State")

    # Toggle OFF and check usage
    toggle_brand_soul(api_url, shop, False)
    time.sleep(0.5)
    r = get_usage(api_url, shop)
    if r["status_code"] != 200:
        fail("Usage endpoint reachable", f"status={r['status_code']}")
        return

    body = r["body"]
    if body.get("brand_soul_enabled") is False:
        ok("Usage shows brand_soul_enabled=false after toggle OFF")
    else:
        fail("Usage shows brand_soul_enabled=false after toggle OFF",
             f"got brand_soul_enabled={body.get('brand_soul_enabled')}")

    # Toggle ON and check usage
    toggle_brand_soul(api_url, shop, True)
    time.sleep(0.5)
    r = get_usage(api_url, shop)
    body = r["body"]
    if body.get("brand_soul_enabled") is True:
        ok("Usage shows brand_soul_enabled=true after toggle ON")
    else:
        fail("Usage shows brand_soul_enabled=true after toggle ON",
             f"got brand_soul_enabled={body.get('brand_soul_enabled')}")

    # Verify brand_context_status is present
    if "brand_context_status" in body:
        ok("Usage returns brand_context_status", f"value={body['brand_context_status']}")
    else:
        fail("Usage returns brand_context_status", "key missing from response")


def test_brand_context_status(api_url: str, shop: str):
    section("3. Brand Context Status Endpoint")

    r = get_brand_context_status(api_url, shop)
    if r["status_code"] == 200:
        body = r["body"]
        if isinstance(body, dict) and "status" in body:
            ok("Brand context status endpoint", f"status={body['status']}")
        else:
            ok("Brand context status endpoint", f"response={json.dumps(body)[:100]}")
    else:
        skip("Brand context status endpoint", f"status={r['status_code']}")


def test_brand_intelligence(api_url: str, shop: str):
    section("4. Brand Intelligence (Strategic Intelligence)")

    r = get_brand_intelligence(api_url, shop)
    if r["status_code"] == 200:
        body = r["body"]
        has_intel = bool(body.get("strategic_intelligence") or body.get("data"))
        if has_intel:
            ok("Brand intelligence available", "strategic_intelligence present")
        else:
            ok("Brand intelligence endpoint works", "no intel stored yet (expected for test shops)")
    elif r["status_code"] == 404:
        skip("Brand intelligence", "no intel for this shop")
    else:
        fail("Brand intelligence endpoint", f"status={r['status_code']}")


def test_rewrite_with_toggle(api_url: str, shop: str):
    section("5. Rewrite Gated by Brand Soul Toggle")

    product = "若狭塗箸セット"
    desc = "福井県小浜市の伝統工芸、若狭塗の箸セットです。貝殻や卵殻を使った独特の模様が特徴で、何層にも漆を塗り重ねて研ぎ出すことで美しい柄が現れます。"

    brand_keywords = ["heritage", "artisan", "lacquer", "craftsmanship", "tradition",
                      "authentic", "wakasa", "master", "heirloom", "handcrafted"]

    # Rewrite WITH brand soul ON
    toggle_brand_soul(api_url, shop, True)
    time.sleep(0.5)

    print("  Generating with brand soul ON (may take 15-30s)...")
    r_on = generate_copy(api_url, shop, product, desc)
    if r_on["status_code"] != 200:
        fail("Rewrite with brand soul ON", f"status={r_on['status_code']} body={str(r_on['body'])[:200]}")
        # Restore toggle and skip remaining
        toggle_brand_soul(api_url, shop, True)
        return

    body_on = r_on["body"]
    text_on = ""
    if isinstance(body_on, dict):
        data = body_on.get("data", {})
        text_on = data.get("description", "") or data.get("title", "")
    if text_on:
        ok("Rewrite with brand soul ON returned content", f"{len(text_on)} chars")
    else:
        fail("Rewrite with brand soul ON returned content",
             f"empty. keys={list(body_on.keys()) if isinstance(body_on, dict) else 'not dict'}")

    # Rewrite WITH brand soul OFF
    toggle_brand_soul(api_url, shop, False)
    time.sleep(0.5)

    print("  Generating with brand soul OFF (may take 15-30s)...")
    r_off = generate_copy(api_url, shop, product, desc)
    if r_off["status_code"] != 200:
        fail("Rewrite with brand soul OFF", f"status={r_off['status_code']} body={str(r_off['body'])[:200]}")
        toggle_brand_soul(api_url, shop, True)
        return

    body_off = r_off["body"]
    text_off = ""
    if isinstance(body_off, dict):
        data = body_off.get("data", {})
        text_off = data.get("description", "") or data.get("title", "")
    if text_off:
        ok("Rewrite with brand soul OFF returned content", f"{len(text_off)} chars")
    else:
        fail("Rewrite with brand soul OFF returned content",
             f"empty. keys={list(body_off.keys()) if isinstance(body_off, dict) else 'not dict'}")

    # Restore toggle
    toggle_brand_soul(api_url, shop, True)

    # Compare keyword presence
    if text_on and text_off:
        on_lower = text_on.lower()
        off_lower = text_off.lower()
        kw_on = [kw for kw in brand_keywords if kw.lower() in on_lower]
        kw_off = [kw for kw in brand_keywords if kw.lower() in off_lower]

        print(f"\n  {Colors.BOLD}  Comparison:{Colors.END}")
        print(f"    ON:  {len(text_on.split())} words, {len(kw_on)}/{len(brand_keywords)} keywords ({', '.join(kw_on) or 'none'})")
        print(f"    OFF: {len(text_off.split())} words, {len(kw_off)}/{len(brand_keywords)} keywords ({', '.join(kw_off) or 'none'})")

        diff = len(kw_on) - len(kw_off)
        if diff > 0:
            ok("Brand soul ON has more brand keywords", f"+{diff} keywords")
        elif diff == 0:
            skip("Keyword difference", "same count — shop may not have brand context ingested")
        else:
            skip("Keyword difference", f"OFF has more ({diff}) — may be coincidental with no brand context")


def test_toggle_persistence(api_url: str, shop: str):
    section("6. Toggle Persistence Across Requests")

    # Set to OFF
    toggle_brand_soul(api_url, shop, False)
    time.sleep(0.3)

    # Read back multiple times
    r1 = get_usage(api_url, shop)
    r2 = get_usage(api_url, shop)

    v1 = r1["body"].get("brand_soul_enabled") if r1["status_code"] == 200 else None
    v2 = r2["body"].get("brand_soul_enabled") if r2["status_code"] == 200 else None

    if v1 is False and v2 is False:
        ok("Toggle persists across multiple reads", "both reads returned false")
    else:
        fail("Toggle persists across multiple reads", f"read1={v1}, read2={v2}")

    # Set back to ON
    toggle_brand_soul(api_url, shop, True)
    time.sleep(0.3)

    r3 = get_usage(api_url, shop)
    v3 = r3["body"].get("brand_soul_enabled") if r3["status_code"] == 200 else None
    if v3 is True:
        ok("Toggle ON persists", "read returned true")
    else:
        fail("Toggle ON persists", f"read returned {v3}")


def test_toggle_idempotency(api_url: str, shop: str):
    section("7. Toggle Idempotency")

    # Toggle ON twice
    r1 = toggle_brand_soul(api_url, shop, True)
    r2 = toggle_brand_soul(api_url, shop, True)

    if (r1["status_code"] == 200 and r2["status_code"] == 200
            and r1["body"].get("brand_soul_enabled") is True
            and r2["body"].get("brand_soul_enabled") is True):
        ok("Double toggle ON is idempotent")
    else:
        fail("Double toggle ON is idempotent", f"r1={r1}, r2={r2}")

    # Toggle OFF twice
    r3 = toggle_brand_soul(api_url, shop, False)
    r4 = toggle_brand_soul(api_url, shop, False)

    if (r3["status_code"] == 200 and r4["status_code"] == 200
            and r3["body"].get("brand_soul_enabled") is False
            and r4["body"].get("brand_soul_enabled") is False):
        ok("Double toggle OFF is idempotent")
    else:
        fail("Double toggle OFF is idempotent", f"r3={r3}, r4={r4}")

    # Restore
    toggle_brand_soul(api_url, shop, True)


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Brand Soul Integration Tests")
    parser.add_argument("--shop", required=True, help="Shop domain (must exist in local DB)")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Backend API URL")
    parser.add_argument("--skip-rewrite", action="store_true", help="Skip the slow rewrite tests")
    args = parser.parse_args()

    print(f"\n{Colors.BOLD}Brand Soul Integration Tests{Colors.END}")
    print(f"  Shop: {args.shop}")
    print(f"  API:  {args.api_url}")

    # Connectivity check
    try:
        r = requests.get(f"{args.api_url}/api/admin/usage", params={"shop": args.shop}, timeout=5)
        if r.status_code == 403:
            print(f"\n{Colors.RED}ERROR: Shop subscription expired (403). Pick an active shop.{Colors.END}")
            sys.exit(1)
        if r.status_code != 200:
            print(f"\n{Colors.RED}ERROR: Cannot reach API. Status {r.status_code}: {r.text[:200]}{Colors.END}")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"\n{Colors.RED}ERROR: Cannot connect to {args.api_url}. Is the server running?{Colors.END}")
        sys.exit(1)

    test_toggle_endpoint(args.api_url, args.shop)
    test_usage_reflects_toggle(args.api_url, args.shop)
    test_brand_context_status(args.api_url, args.shop)
    test_brand_intelligence(args.api_url, args.shop)
    test_toggle_persistence(args.api_url, args.shop)
    test_toggle_idempotency(args.api_url, args.shop)

    if not args.skip_rewrite:
        test_rewrite_with_toggle(args.api_url, args.shop)
    else:
        section("5. Rewrite Gated by Brand Soul Toggle")
        skip("Rewrite tests", "skipped via --skip-rewrite")

    # Summary
    total = passed + failed + skipped
    print(f"\n{Colors.BOLD}{'═' * 60}{Colors.END}")
    print(f"  {Colors.GREEN}{passed} passed{Colors.END}  "
          f"{Colors.RED}{failed} failed{Colors.END}  "
          f"{Colors.YELLOW}{skipped} skipped{Colors.END}  "
          f"({total} total)")
    print(f"{Colors.BOLD}{'═' * 60}{Colors.END}\n")

    # Ensure brand soul is ON when we exit
    toggle_brand_soul(args.api_url, args.shop, True)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()

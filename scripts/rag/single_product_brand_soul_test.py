import argparse
import json
import os
import sys
import time
from typing import Any

import httpx


DEFAULT_KOTO_GAMA_JP = (
    "【ご挨拶】\n"
    "古都窯（ことがま）は、明治18年（1885年）に京都・東山で開窯しました。\n"
    "私たちは「用の美（Yo-no-bi）」―使ってこそ美しい―という哲学を大切にしています。\n"
    "飾るための器ではなく、日々の食卓で愛される器を目指しています。\n"
)


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def _auth_headers(shop_domain: str) -> dict[str, str]:
    # Backend dev bypass supports: Authorization: Bearer dev-token:<shop-domain>
    return {
        "Authorization": f"Bearer dev-token:{shop_domain}",
        "Content-Type": "application/json",
    }


def _poll_ready(client: httpx.Client, *, shop: str, headers: dict[str, str], timeout_s: int) -> dict[str, Any]:
    start = time.time()
    while True:
        r = client.get(f"/api/admin/brand-context/status?shop={shop}", headers=headers)
        if r.status_code != 200:
            _fail(f"status failed: {r.status_code} {r.text}")
        data = r.json()
        status = str(data.get("status") or "idle")
        if status == "ready":
            return data
        if status == "failed":
            _fail(f"ingestion failed: {data.get('last_error')}")
        if time.time() - start > timeout_s:
            _fail(f"timed out waiting for ingestion (status={status})")
        time.sleep(2)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Single-product Brand Soul ingestion + generate-bulk smoke test (local)."
    )
    ap.add_argument("--api-base", default=os.getenv("API_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--shop", default=os.getenv("SHOP_DOMAIN", "dev-shop.myshopify.com"))
    ap.add_argument("--brand-persona", default="Koto-gama")
    ap.add_argument("--raw-text", default=os.getenv("BRAND_SOUL_RAW_TEXT", ""))
    ap.add_argument("--use-default-jp", action="store_true", help="Use built-in JP sample text from local_rag_cases.json")
    ap.add_argument("--core-pillars", default="", help="Comma-separated pillars (optional)")

    ap.add_argument("--product-name", required=True)
    ap.add_argument("--japanese-description", required=True)
    ap.add_argument("--category", default="Tableware")
    ap.add_argument("--target-locale", default="en")
    ap.add_argument("--brand-soul-enabled", action="store_true", default=True)

    ap.add_argument("--timeout-s", type=int, default=120)
    ap.add_argument("--expect", default="", help="Comma-separated keywords to look for (optional)")
    ap.add_argument("--min-hits", type=int, default=1)
    args = ap.parse_args()

    raw_text = str(args.raw_text or "").strip()
    if args.use_default_jp:
        raw_text = DEFAULT_KOTO_GAMA_JP
    if not raw_text:
        _fail("No raw brand text provided. Use --raw-text ... or --use-default-jp")

    pillars = [p.strip() for p in str(args.core_pillars or "").split(",") if p.strip()]
    headers = _auth_headers(args.shop)

    print("🧪 Brand Soul Single-Product Test")
    print(f"- api_base: {args.api_base}")
    print(f"- shop: {args.shop}")
    print(f"- product: {args.product_name}")
    print(f"- target_locale: {args.target_locale}")

    with httpx.Client(base_url=args.api_base, timeout=float(args.timeout_s)) as client:
        print("\n🚀 Step 1: Ingest Brand Soul (async)")
        ingest_payload = {
            "brand_persona": args.brand_persona,
            "core_pillars": pillars,
            "raw_text": raw_text,
            "urls": [],
        }
        r = client.post("/api/onboarding/brand-soul", headers=headers, json=ingest_payload)
        if r.status_code != 200:
            _fail(f"ingest failed: {r.status_code} {r.text}")
        data = r.json()
        if data.get("status") != "accepted":
            _fail(f"unexpected ingest response: {data}")
        print("✅ Ingestion accepted")

        print("\n⏳ Step 2: Poll status until ready")
        status_data = _poll_ready(client, shop=args.shop, headers=headers, timeout_s=args.timeout_s)
        print("✅ Ingestion ready")
        # Show what the backend thinks the brand_context is
        bc = status_data.get("brand_context")
        try:
            print("brand_context (status endpoint):")
            print(json.dumps(bc, ensure_ascii=False, indent=2))
        except Exception:
            print(f"brand_context (raw): {bc}")

        print("\n🚀 Step 3: Call generate-bulk (single locale)")
        gen_payload = {
            "product_name": args.product_name,
            "japanese_description": args.japanese_description,
            "category": args.category,
            "target_locales": [args.target_locale],
            "brand_soul_enabled": bool(args.brand_soul_enabled),
        }
        g = client.post("/api/proxy/generate-bulk", headers=headers, json=gen_payload)
        if g.status_code != 200:
            _fail(f"generate-bulk failed: {g.status_code} {g.text}")
        out = g.json()
        if out.get("status") != "success":
            _fail(f"unexpected generate response: {out}")

        result = (out.get("results") or {}).get(args.target_locale) or {}
        description = str(result.get("description") or "")
        title = str(result.get("title") or "")
        seo_title = str(result.get("seo_title") or "")
        seo_desc = str(result.get("seo_description") or "")

        print("\n✅ Step 4: Extracted output")
        print(f"title: {title}")
        print(f"seo_title: {seo_title}")
        print(f"seo_description: {seo_desc}")
        print("\n--- description ---")
        print(description)
        print("--- end description ---\n")

        expected = [k.strip() for k in str(args.expect or "").split(",") if k.strip()]
        if expected:
            haystack = " ".join([title, description, seo_title, seo_desc]).lower()
            found = [k for k in expected if k.lower() in haystack]
            print(f"🔎 Keyword check: found={found} expected={expected} min_hits={args.min_hits}")
            if len(found) < int(args.min_hits):
                _fail("missing expected keywords in output")

    print("✅ PASS")


if __name__ == "__main__":
    main()


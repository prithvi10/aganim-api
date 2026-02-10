"""
Writing Studio — Full Local E2E Test

Orchestrates all Writing Studio feature tests in a single run:
  1. Strategic Intelligence Extraction (brand soul → auto intelligence)
  2. Template Listing (GET /api/templates)
  3. Product Template Generation (all 4 product templates)
  4. Marketing Template Generation (all 6 marketing templates)
  5. Brand Intelligence API verification
  6. Knowledge Graph / Entity Metadata verification
  7. Brand consistency validation across outputs

This script uses REAL OpenAI API calls against a running local server.

Prereqs:
  - Local server running (default http://localhost:8000)
  - OPENAI_API_KEY set
  - PostgreSQL running with shopify_translator DB
  - SHOPIFY_API_KEY / SHOPIFY_API_SECRET set for dev auth bypass

Usage:
  python -m scripts.rag.local_writing_studio_full_test
  python -m scripts.rag.local_writing_studio_full_test --skip-ingest   # reuse existing brand soul
  python -m scripts.rag.local_writing_studio_full_test --save-outputs  # save generated content to files
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.main.db.db_models import Shop, StoreContext, Plan, User

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
SHOP_DOMAIN = "writing-studio-e2e.myshopify.com"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shopify_translator")

# ── Rich Japanese brand soul ──
BRAND_SOUL_TEXT = """
【ご挨拶】
古都窯（ことがま）は、明治18年（1885年）に京都・東山で開窯しました。
私たちは「用の美（Yo-no-bi）」―使ってこそ美しい―という哲学を大切にしています。
飾るための器ではなく、日々の食卓で愛される器を目指しています。

【素材へのこだわり】
信楽の陶土と京都の清水焼の技法を融合させた独自の配合を用いています。
全ての釉薬は天然鉱物から手作りし、化学合成の顔料は一切使用しません。
窯焚きは月に一度、4日間にわたり薪窯で焼成します。

【ブランドストーリー】
創業者・古都源太郎は、陶磁器の芸術性と実用性を両立させることを生涯の使命としました。
現在は5代目・古都修が受け継ぎ、現代のライフスタイルに合う器を提案しています。
2019年にはミラノ・デザインウィークに出展し、欧州のシェフたちからも高い評価を受けました。

【大切にしている価値観】
一、手仕事の温もりを大切にする
二、自然との調和を忘れない
三、使う人の暮らしに寄り添う
四、伝統を守りながら革新する
"""

# ── Template test inputs ──
PRODUCT_INPUTS = {
    "product/collection": {
        "collection_name": "Everyday Tableware Collection",
        "category": "Tableware",
        "products": "Blue Glaze Deep Plate, White Porcelain Tea Cup, Matte Black Rice Bowl, Celadon Soy Sauce Dish",
        "target_locale": "en",
    },
    "product/faq": {
        "title": "蒼釉・深皿（24cm）",
        "category": "Tableware",
        "description": "パスタやカレーに最適な深皿です。直径24cm、高さ5cm。電子レンジ使用可、食洗機は推奨しません。桐箱に入れてお届けします。",
        "target_locale": "en",
    },
    "product/landing-hero": {
        "title": "蒼釉・深皿（24cm）",
        "category": "Tableware",
        "description": "天然釉薬と信楽の陶土による独特の青い色合いが特徴の深皿。パスタやカレーに最適。",
        "target_locale": "en",
    },
    "product/blog-post": {
        "topic": "The Ancient Art of Wood-Kiln Firing: How 4 Days of Fire Transform Clay into Heirloom Ceramics",
        "category": "Artisan Techniques",
        "context": "Koto-gama fires its pieces once a month in a traditional wood kiln over 4 continuous days using Shigaraki clay and natural mineral glazes.",
        "target_locale": "en",
    },
}

MARKETING_INPUTS = {
    "marketing/email-launch": {
        "title": "Blue Glaze Deep Plate (24cm)",
        "category": "Tableware",
        "description": "A 24cm deep plate fired in a wood kiln using Shigaraki clay and natural mineral glazes.",
        "launch_date": "2026-03-15",
        "target_locale": "en",
    },
    "marketing/email-abandoned": {
        "title": "Blue Glaze Deep Plate (24cm)",
        "category": "Tableware",
        "price": "¥12,800",
        "target_locale": "en",
    },
    "marketing/email-welcome": {
        "brand_name": "Koto-gama (古都窯)",
        "target_locale": "en",
    },
    "marketing/blog-post": {
        "topic": "The Art of Japanese Tableware: How Heritage Ceramics Transform Your Dining Experience",
        "product_context": "Koto-gama's Blue Glaze Deep Plate — handcrafted 24cm dish, Shigaraki clay, natural mineral glazes, 4-day wood kiln firing.",
        "target_locale": "en",
        "word_count": "800",
    },
    "marketing/ad-facebook": {
        "title": "Blue Glaze Deep Plate (24cm)",
        "category": "Tableware",
        "description": "Handcrafted in Kyoto since 1885. Shigaraki clay, natural mineral glazes, 4-day wood kiln firing.",
        "platform": "Facebook",
        "target_locale": "en",
    },
    "marketing/ad-google": {
        "title": "Blue Glaze Deep Plate (24cm)",
        "category": "Tableware",
        "keywords": "Japanese ceramics, handmade tableware, Kyoto pottery, artisan plates",
        "target_locale": "en",
    },
}

# Keywords to check across ALL outputs for brand consistency
BRAND_KEYWORDS = ["kyoto", "1885", "handcraft", "artisan", "ceramic", "glaze", "kiln"]


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
            shop.current_plan_name = "Pro"
            db.commit()
    finally:
        db.close()


def _poll_ready(client: httpx.Client, shop: str, headers: dict, timeout_s: int = 120) -> None:
    start = time.time()
    while True:
        r = client.get(f"/api/admin/brand-context/status?shop={shop}", headers=headers)
        if r.status_code != 200:
            _fail(f"Status poll failed: {r.status_code} {r.text}")
        data = r.json()
        st = str(data.get("status") or "idle")
        if st == "ready":
            return
        if st == "failed":
            _fail(f"Ingestion failed: {data.get('last_error')}")
        if time.time() - start > timeout_s:
            _fail(f"Timed out (status={st})")
        time.sleep(2)


# ═══════════════════════════════════════════════════════════════════════
# Step 1: Brand Soul Ingest
# ═══════════════════════════════════════════════════════════════════════

def step_ingest_brand_soul(client: httpx.Client, headers: dict) -> None:
    _log("\n" + "=" * 70)
    _log("📥 STEP 1: Brand Soul Ingestion + Auto Intelligence Extraction")
    _log("=" * 70)

    resp = client.post(
        "/api/onboarding/brand-soul",
        json={
            "brand_persona": "Koto-gama (古都窯)",
            "core_pillars": ["1885 heritage", "Yo-no-bi philosophy", "natural materials", "Kyoto craftsmanship"],
            "raw_text": BRAND_SOUL_TEXT,
        },
        headers=headers,
    )
    if resp.status_code != 200:
        _fail(f"Ingest failed: {resp.status_code} {resp.text}")
    data = resp.json()
    if data.get("status") != "accepted":
        _fail(f"Unexpected: {data}")
    _log("✅ Ingestion accepted")

    _log("⏳ Polling until ready...")
    _poll_ready(client, SHOP_DOMAIN, headers, timeout_s=180)
    _log("✅ Brand soul ready")


# ═══════════════════════════════════════════════════════════════════════
# Step 2: Verify Intelligence
# ═══════════════════════════════════════════════════════════════════════

def step_verify_intelligence(client: httpx.Client, headers: dict) -> dict:
    _log("\n" + "=" * 70)
    _log("🧠 STEP 2: Verify Strategic Intelligence")
    _log("=" * 70)

    resp = client.get(f"/api/admin/brand-intelligence?shop={SHOP_DOMAIN}", headers=headers)
    if resp.status_code != 200:
        _fail(f"GET intelligence failed: {resp.status_code} {resp.text}")

    data = resp.json()
    intel = data.get("intelligence")
    if not intel:
        _log("⚠️  Intelligence is null — auto-extraction may not have completed yet")
        _log("   Triggering manual extraction...")
        resp2 = client.post(f"/api/admin/brand-intelligence/extract?shop={SHOP_DOMAIN}", headers=headers)
        if resp2.status_code == 200:
            intel = resp2.json().get("intelligence", {})
            _log("✅ Manual extraction succeeded")
        else:
            _log(f"⚠️  Manual extraction also failed: {resp2.status_code}")

    if intel:
        archetype = intel.get("archetype", "N/A")
        secondary = intel.get("secondary_archetype", "N/A")
        _log(f"   Archetype: {archetype} / {secondary}")
        _log(f"   Power words: {intel.get('power_words', [])[:5]}")
        _log(f"   Banned phrases: {intel.get('banned_phrases', [])[:5]}")
        rules = intel.get("linguistic_rules", {})
        _log(f"   Linguistic rules keys: {list(rules.keys()) if isinstance(rules, dict) else rules}")
        _log("✅ Intelligence verified")
    else:
        _log("⚠️  No intelligence available — continuing anyway")

    return intel or {}


# ═══════════════════════════════════════════════════════════════════════
# Step 3: List Templates
# ═══════════════════════════════════════════════════════════════════════

def step_list_templates(client: httpx.Client, headers: dict) -> list[dict]:
    _log("\n" + "=" * 70)
    _log("📋 STEP 3: List Available Templates")
    _log("=" * 70)

    resp = client.get("/api/templates", headers=headers)
    if resp.status_code != 200:
        _fail(f"GET /api/templates failed: {resp.status_code} {resp.text}")

    templates = resp.json().get("templates", [])
    _log(f"✅ {len(templates)} templates available:")
    for t in templates:
        _log(f"   [{t['category']:10}] {t['id']:30} — {t['name']}")

    return templates


# ═══════════════════════════════════════════════════════════════════════
# Step 4: Generate Product Content
# ═══════════════════════════════════════════════════════════════════════

def step_generate_content(
    client: httpx.Client,
    headers: dict,
    template_inputs: dict[str, dict],
    label: str,
    save_outputs: bool = False,
) -> list[dict]:
    _log(f"\n{'=' * 70}")
    _log(f"🚀 STEP: Generate {label} Content")
    _log(f"{'=' * 70}")

    results = []
    for tid, inputs in template_inputs.items():
        _log(f"\n   ── {tid} ──")
        _log(f"   Inputs: {json.dumps(inputs, ensure_ascii=False)[:180]}...")

        resp = client.post(
            f"/api/generate/{tid}?shop={SHOP_DOMAIN}",
            json=inputs,
            headers=headers,
        )

        if resp.status_code != 200:
            _log(f"   ❌ Failed: {resp.status_code} {resp.text[:200]}")
            results.append({"template_id": tid, "passed": False, "error": resp.text[:200], "content": ""})
            continue

        data = resp.json()
        if data.get("status") != "success":
            _log(f"   ❌ Status: {data.get('status')}")
            results.append({"template_id": tid, "passed": False, "error": str(data), "content": ""})
            continue

        content = data.get("content", "") or data.get("description", "")
        _log(f"   ✅ Generated ({len(str(content))} chars)")

        # Show content preview
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    _log(f"      {k}: {str(v)[:120]}")
        except (json.JSONDecodeError, TypeError):
            _log(f"      Content: {str(content)[:200]}")

        results.append({"template_id": tid, "passed": True, "content": str(content)})

        if save_outputs:
            out_dir = ROOT / "local_test_outputs" / label.lower().replace(" ", "_")
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = tid.replace("/", "_") + ".txt"
            (out_dir / fname).write_text(str(content), encoding="utf-8")
            _log(f"      💾 Saved to {out_dir / fname}")

    return results


# ═══════════════════════════════════════════════════════════════════════
# Step 5: Brand Consistency Check
# ═══════════════════════════════════════════════════════════════════════

def step_brand_consistency(all_results: list[dict]) -> None:
    _log(f"\n{'=' * 70}")
    _log("🔍 STEP: Brand Consistency Check")
    _log(f"{'=' * 70}")

    haystack = " ".join([r.get("content", "") for r in all_results if r["passed"]]).lower()
    total = len([r for r in all_results if r["passed"]])

    _log(f"   Checking {len(BRAND_KEYWORDS)} brand keywords across {total} outputs...")

    found = []
    missing = []
    for kw in BRAND_KEYWORDS:
        if kw.lower() in haystack:
            found.append(kw)
        else:
            missing.append(kw)

    _log(f"   ✅ Found ({len(found)}): {found}")
    if missing:
        _log(f"   ⚠️  Missing ({len(missing)}): {missing}")
    else:
        _log("   ✅ All brand keywords present across outputs")

    coverage = len(found) / len(BRAND_KEYWORDS) * 100 if BRAND_KEYWORDS else 0
    _log(f"   Brand keyword coverage: {coverage:.0f}%")

    if coverage < 40:
        _log("   ❌ Coverage too low — brand soul may not be injected into templates")
    else:
        _log("   ✅ Brand consistency acceptable")


# ═══════════════════════════════════════════════════════════════════════
# Step 6: DB Verification
# ═══════════════════════════════════════════════════════════════════════

def step_verify_db() -> None:
    _log(f"\n{'=' * 70}")
    _log("🗄️  STEP: Database Verification")
    _log(f"{'=' * 70}")

    _, SessionLocal = _get_db()
    db = SessionLocal()
    try:
        shop = db.query(Shop).filter(Shop.domain == SHOP_DOMAIN).first()
        if not shop:
            _log("   ⚠️  Shop not found in DB")
            return

        # Check brand context
        bc = shop.brand_context
        _log(f"   brand_context: {'present' if bc else 'null'}")

        # Check strategic intelligence
        si = shop.strategic_intelligence
        _log(f"   strategic_intelligence: {'present' if si else 'null'}")
        if si:
            _log(f"   strategic_intelligence_updated_at: {shop.strategic_intelligence_updated_at}")

        # Check chunks
        chunks = db.query(StoreContext).filter(StoreContext.shop_id == SHOP_DOMAIN).count()
        _log(f"   store_context rows: {chunks}")

        # Check entity tags
        tagged = 0
        rows = db.query(StoreContext).filter(StoreContext.shop_id == SHOP_DOMAIN).all()
        for r in rows:
            meta = r.metadata_json if isinstance(r.metadata_json, dict) else {}
            if meta.get("entities"):
                tagged += 1
        _log(f"   chunks with entity tags: {tagged}")

        # Check brand entities
        try:
            from src.main.db.db_models import BrandEntity
            entity_count = db.query(BrandEntity).filter(BrandEntity.shop_id == SHOP_DOMAIN).count()
            _log(f"   brand_entity rows: {entity_count}")
        except Exception:
            _log("   brand_entity: table may not exist")

        _log("✅ DB verification complete")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════

def print_final_summary(product_results: list[dict], marketing_results: list[dict]) -> int:
    all_results = product_results + marketing_results
    passed = sum(1 for r in all_results if r["passed"])
    failed = sum(1 for r in all_results if not r["passed"])

    _log(f"\n{'=' * 70}")
    _log("📊 FINAL SUMMARY — Writing Studio E2E")
    _log(f"{'=' * 70}")
    _log(f"\n  Product Templates:")
    for r in product_results:
        s = "✅" if r["passed"] else "❌"
        _log(f"    {s} {r['template_id']}")

    _log(f"\n  Marketing Templates:")
    for r in marketing_results:
        s = "✅" if r["passed"] else "❌"
        _log(f"    {s} {r['template_id']}")

    _log(f"\n  Total: {len(all_results)} | ✅ Passed: {passed} | ❌ Failed: {failed}")

    return failed


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    global API_BASE

    ap = argparse.ArgumentParser(description="Writing Studio — Full Local E2E Test")
    ap.add_argument("--api-base", default=API_BASE)
    ap.add_argument("--skip-ingest", action="store_true", help="Skip brand soul ingestion")
    ap.add_argument("--save-outputs", action="store_true", help="Save generated content to local_test_outputs/")
    args = ap.parse_args()

    API_BASE = args.api_base

    _log("🚦 Writing Studio — Full E2E Test Suite")
    _log(f"   API: {API_BASE}")
    _log(f"   Shop: {SHOP_DOMAIN}")
    _log(f"   Save outputs: {args.save_outputs}")

    if not os.getenv("OPENAI_API_KEY"):
        _fail("OPENAI_API_KEY is not set")

    _, SessionLocal = _get_db()
    _ensure_plan_user_shop(SessionLocal, SHOP_DOMAIN)

    headers = _auth_headers(SHOP_DOMAIN)

    with httpx.Client(base_url=API_BASE, timeout=180.0) as client:
        # Step 1: Ingest
        if not args.skip_ingest:
            step_ingest_brand_soul(client, headers)
        else:
            _log("\n⏭️  Skipping brand soul ingestion")

        # Step 2: Verify intelligence
        step_verify_intelligence(client, headers)

        # Step 3: List templates
        step_list_templates(client, headers)

        # Step 4A: Product templates
        product_results = step_generate_content(
            client, headers, PRODUCT_INPUTS, "Product", save_outputs=args.save_outputs
        )

        # Step 4B: Marketing templates
        marketing_results = step_generate_content(
            client, headers, MARKETING_INPUTS, "Marketing", save_outputs=args.save_outputs
        )

    # Step 5: Brand consistency
    all_results = product_results + marketing_results
    step_brand_consistency(all_results)

    # Step 6: DB verification
    step_verify_db()

    # Final summary
    failures = print_final_summary(product_results, marketing_results)
    if failures:
        _log(f"\n❌ {failures} template(s) failed")
        sys.exit(1)

    _log("\n✅ WRITING STUDIO FULL E2E TEST PASSED")


if __name__ == "__main__":
    main()

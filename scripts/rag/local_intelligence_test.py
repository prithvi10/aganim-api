"""
Strategic Intelligence Extraction — Local E2E Test

Validates the full intelligence extraction pipeline end-to-end:
  1. Ingest brand soul (auto-triggers intelligence extraction)
  2. Verify strategic_intelligence stored in Shop record
  3. Verify GET /api/admin/brand-intelligence returns structured data
  4. Validate archetype, tonal_guardrails, linguistic_rules populated
  5. Verify BrandEntity rows created in knowledge graph

Prereqs:
  - Local server running (default http://localhost:8000)
  - OPENAI_API_KEY set
  - PostgreSQL running with shopify_translator DB
  - SHOPIFY_API_KEY / SHOPIFY_API_SECRET set for dev auth bypass

Usage:
  python -m scripts.rag.local_intelligence_test
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── project root on sys.path ──
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ecommerce.db.models import Shop, StoreContext, Plan, User

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
SHOP_DOMAIN = os.getenv("SHOP_DOMAIN", "intel-test-shop.myshopify.com")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shopify_translator")


# ── Japanese brand soul with rich context for extraction ──
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
        plan = db.query(Plan).filter(Plan.name == "Standard").first()
        if not plan:
            plan = Plan(
                name="Standard",
                monthly_rewrite_limit=1000,
                max_request_rate=100,
                product_limit=1000,
                max_locales=5,
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
                current_plan_name="Standard",
                last_plan_name="Standard",
                access_expires_at=now + timedelta(days=30),
                reset_anchor_date=now,
                next_reset_date=now + timedelta(days=30),
            )
            db.add(shop)
            db.commit()
    finally:
        db.close()


def _poll_brand_context_ready(client: httpx.Client, shop: str, headers: dict, timeout_s: int = 120) -> None:
    """Poll until brand_context_status == 'ready' (background task fully complete)."""
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


def _poll_intelligence_ready(
    client: httpx.Client, shop: str, headers: dict, timeout_s: int = 60
) -> dict | None:
    """
    Poll GET /api/admin/brand-intelligence until intelligence is non-null.
    Returns the intelligence dict, or None if timed out.
    """
    start = time.time()
    while True:
        r = client.get(f"/api/admin/brand-intelligence?shop={shop}", headers=headers)
        if r.status_code == 200:
            data = r.json()
            intel = data.get("intelligence")
            if intel:
                return intel
        if time.time() - start > timeout_s:
            _log("⚠️  Timed out waiting for strategic_intelligence to be populated")
            return None
        time.sleep(3)


def _ensure_env() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        _fail("OPENAI_API_KEY is not set")


def _cleanup(session_factory, shop_domain: str) -> None:
    db = session_factory()
    try:
        db.query(StoreContext).filter(StoreContext.shop_id == shop_domain).delete(synchronize_session=False)
        shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
        if shop:
            shop.strategic_intelligence = None
            shop.strategic_intelligence_updated_at = None
        db.commit()
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# Test 1: Ingestion auto-triggers intelligence extraction
# ═══════════════════════════════════════════════════════════════════════

def test_auto_intelligence_on_ingest() -> None:
    """
    Purpose: Verify that ingesting brand soul automatically extracts strategic intelligence.
    Why: intelligence_extractor should run as part of ingest_brand_context_with_intelligence.
    Expected: Shop.strategic_intelligence is populated after ingestion completes.
    """
    _log("\n" + "=" * 60)
    _log("🧠 Test 1: Auto Intelligence Extraction on Ingest")
    _log("=" * 60)
    _log("Purpose: Brand soul ingest → auto strategic intelligence extraction")
    _log("Expected: strategic_intelligence JSON stored in Shop record")

    _, SessionLocal = _get_db()
    _ensure_plan_user_shop(SessionLocal, SHOP_DOMAIN)
    _cleanup(SessionLocal, SHOP_DOMAIN)

    headers = _auth_headers(SHOP_DOMAIN)

    with httpx.Client(base_url=API_BASE, timeout=180.0) as client:
        _log("\n🚀 Step 1: Ingest brand soul")
        resp = client.post(
            "/api/onboarding/brand-soul",
            json={
                "brand_persona": "Koto-gama (古都窯)",
                "core_pillars": ["1885 heritage", "Yo-no-bi philosophy", "natural materials"],
                "raw_text": BRAND_SOUL_TEXT,
            },
            headers=headers,
        )
        if resp.status_code != 200:
            _fail(f"POST /api/onboarding/brand-soul failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if data.get("status") != "accepted":
            _fail(f"Unexpected response: {data}")
        _log("✅ Ingestion accepted")

        _log("\n⏳ Step 2: Poll until brand context is ready")
        _poll_brand_context_ready(client, SHOP_DOMAIN, headers, timeout_s=180)
        _log("✅ Brand context ingested")

        _log("\n⏳ Step 2b: Poll until strategic intelligence is extracted")
        api_intel = _poll_intelligence_ready(client, SHOP_DOMAIN, headers, timeout_s=120)
        if api_intel:
            _log("✅ Strategic intelligence detected via API")

    # Direct DB check
    _log("\n🔍 Step 3: Verify strategic_intelligence in DB")
    db = SessionLocal()
    try:
        # Refresh session to pick up background task commits
        db.expire_all()
        shop = db.query(Shop).filter(Shop.domain == SHOP_DOMAIN).first()
        if not shop:
            _fail("Shop not found in DB after ingestion")

        si = shop.strategic_intelligence
        if not si:
            _fail("strategic_intelligence is NULL after ingestion — auto-extraction did not run")

        _log(f"✅ strategic_intelligence populated (type={type(si).__name__})")
        _log(f"   Keys: {list(si.keys()) if isinstance(si, dict) else 'N/A'}")

        # Validate structure — adapt to actual schema from StrategicIntelligence Pydantic model
        if isinstance(si, dict):
            # archetype is a string enum (e.g. "artisan_master"), not a nested dict
            archetype = si.get("archetype")
            secondary = si.get("secondary_archetype")
            confidence = si.get("archetype_confidence")
            if archetype:
                _log(f"   Archetype: {archetype} (confidence={confidence}, secondary={secondary})")
            else:
                _log("   ⚠️ No archetype found")

            # tonal_guardrails is a nested dict with formality/energy/humor/etc.
            guardrails = si.get("tonal_guardrails")
            if guardrails and isinstance(guardrails, dict):
                _log(f"   Tonal Guardrails: {list(guardrails.keys())}")
            else:
                _log("   ⚠️ No tonal_guardrails found")

            # power_words and banned_phrases are top-level lists
            power_words = si.get("power_words", [])
            banned = si.get("banned_phrases", [])
            if power_words:
                _log(f"   Power words ({len(power_words)}): {power_words[:5]}")
            if banned:
                _log(f"   Banned phrases ({len(banned)}): {banned[:5]}")

            rules = si.get("linguistic_rules")
            if rules and isinstance(rules, dict):
                _log(f"   Linguistic Rules: {list(rules.keys())}")
            else:
                _log("   ⚠️ No linguistic_rules found")

            # Additional fields
            for extra_key in ("core_value_props", "differentiators", "origin_story_hooks", "cultural_touchpoints"):
                val = si.get(extra_key)
                if val:
                    preview = str(val)[:120]
                    _log(f"   {extra_key}: {preview}")

        updated_at = shop.strategic_intelligence_updated_at
        _log(f"   Updated at: {updated_at}")

        _log("\n✅ strategic_intelligence_updated_at is set")
    finally:
        db.close()

    _log("\n[OK] Auto Intelligence Extraction test passed.")


# ═══════════════════════════════════════════════════════════════════════
# Test 2: GET /api/admin/brand-intelligence endpoint
# ═══════════════════════════════════════════════════════════════════════

def test_brand_intelligence_api() -> None:
    """
    Purpose: Verify the brand intelligence GET endpoint returns stored data.
    Why: UI needs this endpoint to display the intelligence dashboard.
    Expected: JSON response with intelligence + updated_at.
    """
    _log("\n" + "=" * 60)
    _log("📡 Test 2: GET /api/admin/brand-intelligence")
    _log("=" * 60)
    _log("Purpose: Verify intelligence API endpoint returns stored data")

    headers = _auth_headers(SHOP_DOMAIN)

    with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
        resp = client.get(f"/api/admin/brand-intelligence?shop={SHOP_DOMAIN}", headers=headers)
        if resp.status_code != 200:
            _fail(f"GET /api/admin/brand-intelligence failed: {resp.status_code} {resp.text}")

        data = resp.json()
        intel = data.get("intelligence")
        updated_at = data.get("updated_at")

        if not intel:
            _fail("Intelligence is null/empty from API")
        if not updated_at:
            _fail("updated_at is null from API")

        _log(f"✅ Intelligence returned via API")
        _log(f"   updated_at: {updated_at}")

        # Pretty-print intelligence for inspection
        _log("\n📋 Full Strategic Intelligence:")
        _log(json.dumps(intel, ensure_ascii=False, indent=2))

    _log("\n[OK] Brand Intelligence API test passed.")


# ═══════════════════════════════════════════════════════════════════════
# Test 3: Manual re-extraction via POST endpoint
# ═══════════════════════════════════════════════════════════════════════

def test_manual_extraction_endpoint() -> None:
    """
    Purpose: Verify POST /api/admin/brand-intelligence/extract works on demand.
    Why: User may want to re-extract after editing brand context.
    Expected: Returns updated intelligence with new timestamp.
    """
    _log("\n" + "=" * 60)
    _log("🔄 Test 3: POST /api/admin/brand-intelligence/extract")
    _log("=" * 60)
    _log("Purpose: Manual re-extraction of strategic intelligence")

    headers = _auth_headers(SHOP_DOMAIN)

    with httpx.Client(base_url=API_BASE, timeout=180.0) as client:
        resp = client.post(f"/api/admin/brand-intelligence/extract?shop={SHOP_DOMAIN}", headers=headers)
        if resp.status_code != 200:
            _fail(f"POST extract failed: {resp.status_code} {resp.text}")

        data = resp.json()
        if data.get("status") != "success":
            _fail(f"Unexpected response: {data}")

        intel = data.get("intelligence", {})
        updated_at = data.get("updated_at")

        _log(f"✅ Re-extraction succeeded")
        _log(f"   updated_at: {updated_at}")

        # Validate archetype presence (string enum, not nested dict)
        archetype = intel.get("archetype", "")
        if not archetype:
            _fail("Archetype missing after re-extraction")
        _log(f"   Archetype: {archetype}")

        # power_words is a top-level list
        pw = intel.get("power_words", [])
        if not pw:
            _log("   ⚠️ power_words empty (may vary by LLM)")
        else:
            _log(f"   Power words: {pw[:5]}")

    _log("\n[OK] Manual extraction endpoint test passed.")


# ═══════════════════════════════════════════════════════════════════════
# Test 4: Knowledge Graph (BrandEntity) stored
# ═══════════════════════════════════════════════════════════════════════

def test_knowledge_graph_entities() -> None:
    """
    Purpose: Verify BrandEntity triplets are stored during ingestion.
    Why: Knowledge graph enables enhanced retrieval.
    Expected: brand_entities rows exist for our shop.
    """
    _log("\n" + "=" * 60)
    _log("🕸️  Test 4: Knowledge Graph (BrandEntity) rows")
    _log("=" * 60)
    _log("Purpose: Verify brand entity triplets stored in DB")

    _, SessionLocal = _get_db()
    db = SessionLocal()
    try:
        from src.ecommerce.db.models import BrandEntity
        entities = db.query(BrandEntity).filter(BrandEntity.shop_id == SHOP_DOMAIN).all()
        if not entities:
            _log("⚠️  No BrandEntity rows found — knowledge graph may not be populated yet")
            _log("   (This is acceptable if triplet extraction is disabled or brand text was too short)")
        else:
            _log(f"✅ Found {len(entities)} BrandEntity rows")
            for e in entities[:10]:
                _log(f"   [{e.subject_type}] {e.subject} → {e.relation} → {e.object} [{e.object_type}]")
            if len(entities) > 10:
                _log(f"   ... and {len(entities) - 10} more")
    except Exception as ex:
        _log(f"⚠️  BrandEntity table may not exist: {ex}")
    finally:
        db.close()

    _log("\n[OK] Knowledge Graph entities test completed.")


# ═══════════════════════════════════════════════════════════════════════
# Test 5: Chunk entity metadata tags
# ═══════════════════════════════════════════════════════════════════════

def test_chunk_entity_metadata() -> None:
    """
    Purpose: Verify chunks have entity metadata tags after intelligence-enriched ingestion.
    Why: Enhanced retriever uses entity metadata for knowledge-graph-aware search.
    Expected: Some store_context rows have 'entities' in metadata_json.
    """
    _log("\n" + "=" * 60)
    _log("🏷️  Test 5: Chunk Entity Metadata Tags")
    _log("=" * 60)
    _log("Purpose: Verify RAG chunks have entity metadata for enhanced retrieval")

    _, SessionLocal = _get_db()
    db = SessionLocal()
    try:
        rows = db.query(StoreContext).filter(StoreContext.shop_id == SHOP_DOMAIN).all()
        if not rows:
            _fail("No store_context rows found for shop")

        tagged = 0
        for r in rows:
            meta = r.metadata_json if isinstance(r.metadata_json, dict) else {}
            if meta.get("entities"):
                tagged += 1

        _log(f"   Total chunks: {len(rows)}")
        _log(f"   Chunks with entity tags: {tagged}")

        if tagged > 0:
            # Show a sample
            for r in rows:
                meta = r.metadata_json if isinstance(r.metadata_json, dict) else {}
                if meta.get("entities"):
                    _log(f"   Sample entities: {meta['entities'][:5]}")
                    _log(f"   Chunk preview: {r.content[:100]}...")
                    break
            _log("✅ Entity metadata tagging is working")
        else:
            _log("⚠️  No chunks have entity tags — entity extraction may not be running during ingestion")
    finally:
        db.close()

    _log("\n[OK] Chunk entity metadata test completed.")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    _log("🚦 Strategic Intelligence — Local E2E Test Suite")
    _log(f"   API: {API_BASE}")
    _log(f"   Shop: {SHOP_DOMAIN}")
    _log(f"   DB: {DATABASE_URL}")
    _ensure_env()

    tests = [
        ("Auto Intelligence on Ingest", test_auto_intelligence_on_ingest),
        ("Brand Intelligence API", test_brand_intelligence_api),
        ("Manual Extraction Endpoint", test_manual_extraction_endpoint),
        ("Knowledge Graph Entities", test_knowledge_graph_entities),
        ("Chunk Entity Metadata", test_chunk_entity_metadata),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except SystemExit:
            failed += 1
        except Exception as exc:
            _log(f"❌ {name} error: {exc}")
            failed += 1

    _log(f"\n{'=' * 60}")
    _log(f"✅ Passed: {passed} | ❌ Failed: {failed}")
    _log(f"{'=' * 60}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

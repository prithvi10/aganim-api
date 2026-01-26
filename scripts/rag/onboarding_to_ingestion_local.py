import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.main.db.db_models import StoreContext, Shop, Plan, User
from src.main.service.brand_context_retrieval import get_brand_context


API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
# dev-token-123 resolves to this shop in verify_shopify_session
SHOP_DOMAIN = os.getenv("SHOP_DOMAIN", "dev-shop.myshopify.com")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shopify_translator")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def _log(msg: str) -> None:
    print(msg)


def _ensure_env() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        _fail("OPENAI_API_KEY is not set")
    if not os.getenv("SHOPIFY_API_KEY") or not os.getenv("SHOPIFY_API_SECRET"):
        _fail("SHOPIFY_API_KEY/SHOPIFY_API_SECRET must be set for auth bypass")


def _get_db():
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, SessionLocal


def test_onboarding_to_ingestion() -> None:
    """
    Purpose: Validate that Brand Soul onboarding triggers async ingestion, stores chunks, and embeds.
    Why: Ensures ingestion pipeline is working end-to-end before enabling RAG in production.
    Expected output: store_context rows exist, embeddings length=1536, and chunks contain key pillars.
    """
    _log("🧭 Purpose: Onboarding -> Ingestion end-to-end")
    _log("✅ Expected: chunks + embeddings stored for Brand Soul")

    payload = {
        "brand_persona": "Artisan Master",
        "core_pillars": ["200-year history", "Hand-painted", "Gifu Province"],
    }
    headers = {"Authorization": "Bearer dev-token-123", "Content-Type": "application/json"}

    _, SessionLocal = _get_db()
    db = SessionLocal()
    try:
        existing = db.query(Shop).filter(Shop.domain == SHOP_DOMAIN).first()
        if not existing:
            db.add(Shop(domain=SHOP_DOMAIN, access_token=""))
            db.commit()
    finally:
        db.close()
    _log("✅ Shop ensured in DB")

    with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
        _log("🚀 Calling /api/onboarding/brand-soul")
        resp = client.post("/api/onboarding/brand-soul", json=payload, headers=headers)
        if resp.status_code != 200:
            _fail(f"POST /api/onboarding/brand-soul failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if data.get("status") != "accepted":
            _fail(f"Unexpected response: {data}")
        _log("✅ Ingestion accepted")

        # Poll status until ready or failed.
        status = "idle"
        for _ in range(30):
            _log("⏳ Polling /api/admin/brand-context/status")
            s = client.get(f"/api/admin/brand-context/status?shop={SHOP_DOMAIN}", headers=headers)
            if s.status_code != 200:
                _fail(f"Status check failed: {s.status_code} {s.text}")
            sdata = s.json()
            status = str(sdata.get("status") or "idle")
            if status == "ready":
                break
            if status == "failed":
                _fail(f"Ingestion failed: {sdata.get('last_error')}")
            time.sleep(2)

    if status != "ready":
        _fail("Timed out waiting for brand context ingestion")
    _log("✅ Ingestion completed")

    db = SessionLocal()
    try:
        rows = db.query(StoreContext).filter(StoreContext.shop_id == SHOP_DOMAIN).all()
        if not rows:
            _fail("No store_context rows found for shop")
        _log(f"✅ Found {len(rows)} store_context rows")

        contents = " ".join([r.content for r in rows]).lower()
        patterns = {
            "200-year history": ["200-year", "200 year", "200-year history", "200 year history"],
            "Hand-painted": ["hand-painted", "hand painted"],
            "Gifu Province": ["gifu", "gifu province"],
        }
        matched = 0
        for label, opts in patterns.items():
            if any(opt in contents for opt in opts):
                matched += 1
            else:
                print(f"[WARN] Missing expected token in chunks: {label}")
        if matched < 2:
            _fail("Missing too many expected tokens in chunks (need >=2)")
        _log("✅ Pillar tokens validated")

        emb = rows[0].embedding
        if isinstance(emb, str):
            emb = json.loads(emb)
        if len(emb) != 1536:
            _fail(f"Embedding length != 1536 (got {len(emb)})")
        _log("✅ Embedding length is 1536")

        print("[OK] Onboarding -> ingestion test passed.")
    finally:
        db.query(StoreContext).filter(StoreContext.shop_id == SHOP_DOMAIN).delete(synchronize_session=False)
        db.query(Shop).filter(Shop.domain == SHOP_DOMAIN).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_rewriter_rag_injection() -> None:
    """
    Purpose: Verify RAG brand context is injected into the prompt and appears in output.
    Why: Ensures product optimization actually uses Brand Soul context.
    Expected output: Prompt contains BRAND_HERITAGE_CONTEXT + Arita-yaki; description mentions heritage.
    """
    _log("🧭 Purpose: Rewriter RAG injection into prompt + output")
    _log("✅ Expected: Arita-yaki appears in prompt and output")

    headers = {"Authorization": "Bearer dev-token-123", "Content-Type": "application/json"}
    payload = {
        "product_name": "Blue Ceramic Plate",
        "japanese_description": "美しい青い陶器の皿。伝統的な技法で作られています。",
        "category": "Tableware",
        "target_locales": ["en"],
        "brand_soul_enabled": True,
    }

    engine, SessionLocal = _get_db()
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        # Ensure Plan/User/Shop exist for gating
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

        user = db.query(User).filter(User.username == SHOP_DOMAIN).first()
        if not user:
            user = User(username=SHOP_DOMAIN, email=None, plan_id=plan.id)
            db.add(user)
            db.commit()

        shop = db.query(Shop).filter(Shop.domain == SHOP_DOMAIN).first()
        if not shop:
            shop = Shop(
                domain=SHOP_DOMAIN,
                access_token="",
                current_plan_name="Standard",
                last_plan_name="Standard",
                access_expires_at=now + timedelta(days=30),
                reset_anchor_date=now,
                next_reset_date=now + timedelta(days=30),
            )
            db.add(shop)
            db.commit()

        # Seed brand context: Arita-yaki
        db.query(StoreContext).filter(StoreContext.shop_id == SHOP_DOMAIN).delete(
            synchronize_session=False
        )
        db.add(
            StoreContext(
                shop_id=SHOP_DOMAIN,
                content="We use Arita-yaki porcelain techniques for every piece.",
                embedding=[0.0] * 1536,
                metadata_json={"source_type": "seed"},
            )
        )
        db.commit()
        _log("✅ Brand context seeded")
    finally:
        db.close()

    prompt_trace_path = os.getenv("BRAND_PROMPT_TRACE_PATH", "./tmp/brand_prompt_trace.txt")
    _log(f"Using API base: {API_BASE}")
    _log(f"Expecting prompt trace at: {prompt_trace_path}")

    with httpx.Client(base_url=API_BASE, timeout=180.0) as client:
        resp = None
        for attempt in range(2):
            try:
                _log(f"🚀 Calling /api/proxy/generate-bulk (attempt {attempt + 1})")
                resp = client.post("/api/proxy/generate-bulk", json=payload, headers=headers)
                break
            except httpx.ReadTimeout:
                _log("⏱️ ReadTimeout on generate-bulk")
                if attempt == 1:
                    _fail("POST /api/proxy/generate-bulk timed out")
        if not resp or resp.status_code != 200:
            _fail(f"POST /api/proxy/generate-bulk failed: {getattr(resp, 'status_code', None)} {getattr(resp, 'text', '')}")
        data = resp.json()
        if data.get("status") != "success":
            _fail(f"Unexpected response: {data}")
        _log("✅ Generate-bulk succeeded")

    # Read captured prompt (optional)
    prompt_path = prompt_trace_path
    prompt = ""
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()
    else:
        alt_path = os.path.abspath("./tmp/brand_prompt_trace.txt")
        if os.path.exists(alt_path):
            _log(f"Prompt trace not found at {prompt_path}, using {alt_path}")
            with open(alt_path, "r", encoding="utf-8") as f:
                prompt = f.read()
        else:
            _log(f"⚠️ Prompt trace missing at {prompt_path}; skipping prompt assertion")

    if prompt:
        if "BRAND_HERITAGE_CONTEXT" not in prompt or "Arita-yaki" not in prompt:
            _fail("Arita-yaki missing from BRAND_HERITAGE_CONTEXT in system prompt")
        _log("✅ Prompt injection verified")

    result = data.get("results", {}).get("en") or data.get("data") or {}
    description = str(result.get("description") or "")
    seo_title = str(result.get("seo_title") or "")
    seo_desc = str(result.get("seo_description") or "")
    _log(f"Description snippet: {description[:220]}")
    _log(f"SEO title: {seo_title}")
    _log(f"SEO description: {seo_desc}")
    heritage_hits = ["arita-yaki", "arita"]
    haystack = " ".join([description, seo_title, seo_desc]).lower()
    if not any(h in haystack for h in heritage_hits):
        _fail("OpenAI response did not weave Arita-yaki heritage into output (description/SEO)")
    _log("✅ Output includes heritage")

    # Cleanup
    db = SessionLocal()
    try:
        db.query(StoreContext).filter(StoreContext.shop_id == SHOP_DOMAIN).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    print("[OK] Rewriter RAG injection test passed.")


def test_multi_tenant_wall() -> None:
    """
    Purpose: Ensure Shop_A retrieval never leaks Shop_B content.
    Why: Prevents cross-merchant data leakage in RAG retrieval.
    Expected output: Shop_A results contain zero Shop_B mentions.
    """
    _log("🧭 Purpose: Multi-tenant wall (Shop_A vs Shop_B)")
    _log("✅ Expected: Shop_A results contain 0% Shop_B content")

    engine, SessionLocal = _get_db()
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
    except Exception as e:
        _fail(f"pgvector extension setup failed: {e}")

    shop_a = "shop_a.myshopify.com"
    shop_b = "shop_b.myshopify.com"
    db = SessionLocal()
    try:
        _log("🧹 Cleaning old rows for Shop_A and Shop_B")
        db.query(StoreContext).filter(StoreContext.shop_id.in_([shop_a, shop_b])).delete(
            synchronize_session=False
        )
        db.commit()

        _log("🧪 Seeding Shop_A automotive content")
        db.add_all(
            [
                StoreContext(
                    shop_id=shop_a,
                    content="Automotive parts brand story: precision engineering.",
                    embedding=[0.0] * 1536,
                    metadata_json={"source_type": "seed"},
                ),
                StoreContext(
                    shop_id=shop_a,
                    content="High-performance brake components for reliability.",
                    embedding=[0.0] * 1536,
                    metadata_json={"source_type": "seed"},
                ),
            ]
        )

        _log("🧪 Seeding Shop_B kimono content")
        db.add_all(
            [
                StoreContext(
                    shop_id=shop_b,
                    content="Kimono heritage: silk fabric and traditional patterns.",
                    embedding=[1.0] * 1536,
                    metadata_json={"source_type": "seed"},
                ),
                StoreContext(
                    shop_id=shop_b,
                    content="Luxurious kimono textiles crafted with artistry.",
                    embedding=[1.0] * 1536,
                    metadata_json={"source_type": "seed"},
                ),
            ]
        )
        db.commit()

        _log("🔎 Running get_brand_context for Shop_A with query 'High quality fabric'")
        results = get_brand_context(db, shop_id=shop_a, product_text="High quality fabric", limit=3)
        if not results:
            _fail("No results returned for Shop_A (expected at least one)")

        combined = " ".join([r.get("content", "") for r in results]).lower()
        if "kimono" in combined or "silk" in combined:
            _fail("Shop_B content leaked into Shop_A results")

        _log("✅ Shop_A results contain no Shop_B content")
        print("[OK] Multi-tenant wall test passed.")
    finally:
        _log("🧽 Cleanup seeded rows")
        db.query(StoreContext).filter(StoreContext.shop_id.in_([shop_a, shop_b])).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()

def main() -> None:
    _log("🚦 Running local RAG test suite")
    _ensure_env()
    test_onboarding_to_ingestion()
    print("\n")
    test_rewriter_rag_injection()
    print("\n")
    test_multi_tenant_wall()


if __name__ == "__main__":
    main()

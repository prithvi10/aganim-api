import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.main.db.db_models import StoreContext, Shop, Plan, User
from src.main.service.brand_context_retrieval import get_brand_context


API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
# dev-token-123 resolves to this shop in verify_shopify_session
SHOP_DOMAIN = os.getenv("SHOP_DOMAIN", "dev-shop.myshopify.com")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shopify_translator")
RAG_CASES_PATH = os.getenv("RAG_CASES_PATH", "scripts/rag/local_rag_cases.json")


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


def _auth_headers(shop_domain: str) -> dict:
    return {
        "Authorization": f"Bearer dev-token:{shop_domain}",
        "Content-Type": "application/json",
    }


def _poll_brand_context_ready(client: httpx.Client, shop_domain: str, headers: dict) -> None:
    status = "idle"
    for _ in range(40):
        _log("⏳ Polling /api/admin/brand-context/status")
        s = client.get(f"/api/admin/brand-context/status?shop={shop_domain}", headers=headers)
        if s.status_code != 200:
            _fail(f"Status check failed: {s.status_code} {s.text}")
        sdata = s.json()
        status = str(sdata.get("status") or "idle")
        if status == "ready":
            return
        if status == "failed":
            _fail(f"Ingestion failed: {sdata.get('last_error')}")
        time.sleep(2)
    _fail("Timed out waiting for brand context ingestion")


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
    headers = _auth_headers(SHOP_DOMAIN)

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

        _poll_brand_context_ready(client, SHOP_DOMAIN, headers)
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

    headers = _auth_headers(SHOP_DOMAIN)
    payload = {
        "product_name": "Blue Ceramic Plate",
        "japanese_description": "美しい青い陶器の皿。伝統的な技法で作られています。",
        "category": "Tableware",
        "target_locales": ["en"],
        "brand_soul_enabled": True,
    }

    _, SessionLocal = _get_db()
    _ensure_plan_user_shop(SessionLocal, SHOP_DOMAIN)
    db = SessionLocal()
    try:
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


def test_brand_soul_about_us_case() -> None:
    """
    Purpose: Ingest Japanese "About Us" content and verify RAG injects traceable facts.
    Why: Ensures real-world brand soul text influences output for a product description.
    Expected output: Output mentions at least 2 traceable facts (history/year, Kyoto/Higashiyama, Yo-no-bi).
    """
    _log("🧭 Purpose: Brand Soul About Us + Product RAG (JP input)")
    _log("✅ Expected: Output contains traceable facts from About Us")

    shop_domain = "brand-soul-kyoto.myshopify.com"
    headers = _auth_headers(shop_domain)

    brand_soul_text = (
        "【ご挨拶】\n"
        "古都窯（ことがま）は、明治18年（1885年）に京都・東山で開窯しました。\n"
        "私たちは「用の美（Yo-no-bi）」―使ってこそ美しい―という哲学を大切にしています。\n"
        "飾るための器ではなく、日々の食卓で愛される器を目指しています。\n"
    )

    product_text = (
        "商品名: 蒼釉・深皿（24cm）\n"
        "説明: パスタやカレーに最適な深皿です。"
        " 直径24cm、高さ5cm。 電子レンジ使用可、食洗機は推奨しません。 桐箱に入れてお届けします。"
    )

    _, SessionLocal = _get_db()
    _ensure_plan_user_shop(SessionLocal, shop_domain)

    with httpx.Client(base_url=API_BASE, timeout=60.0) as client:
        _log("🚀 Calling /api/onboarding/brand-soul with raw About Us content")
        resp = client.post(
            "/api/onboarding/brand-soul",
            json={"brand_persona": "Koto-gama", "core_pillars": [], "raw_text": brand_soul_text},
            headers=headers,
        )
        if resp.status_code != 200:
            _fail(f"POST /api/onboarding/brand-soul failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if data.get("status") != "accepted":
            _fail(f"Unexpected response: {data}")
        _log("✅ Ingestion accepted")

        _poll_brand_context_ready(client, shop_domain, headers)
        _log("✅ Ingestion completed")

        _log("🚀 Calling /api/proxy/generate-bulk with product input")
        resp = client.post(
            "/api/proxy/generate-bulk",
            json={
                "product_name": "蒼釉・深皿（24cm）",
                "japanese_description": product_text,
                "category": "Tableware",
                "target_locales": ["en"],
                "brand_soul_enabled": True,
            },
            headers=headers,
        )
        if resp.status_code != 200:
            _fail(f"POST /api/proxy/generate-bulk failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if data.get("status") != "success":
            _fail(f"Unexpected response: {data}")

        result = data.get("results", {}).get("en") or {}
        description = str(result.get("description") or "")
        seo_title = str(result.get("seo_title") or "")
        seo_desc = str(result.get("seo_description") or "")
        haystack = " ".join([description, seo_title, seo_desc]).lower()

        facts = {
            "1885": ["1885", "meiji 18", "meiji-era 1885"],
            "kyoto": ["kyoto", "higashiyama"],
            "yo-no-bi": ["yo-no-bi", "yo no bi", "yō-no-bi", "yo‑no‑bi"],
        }
        hits = 0
        for label, opts in facts.items():
            if any(opt in haystack for opt in opts):
                hits += 1
            else:
                print(f"[WARN] Missing traceable fact: {label}")
        if hits < 2:
            _fail("Output missing too many traceable facts (need >=2)")

        _log("✅ Output includes traceable facts")
        print("[OK] Brand Soul About Us test passed.")

    db = SessionLocal()
    try:
        db.query(StoreContext).filter(StoreContext.shop_id == shop_domain).delete(
            synchronize_session=False
        )
        db.query(Shop).filter(Shop.domain == shop_domain).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def _load_cases_config(path: str) -> dict:
    if not os.path.exists(path):
        _fail(f"Config file not found: {path}")
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if path.endswith((".yml", ".yaml")):
        try:
            import yaml  # type: ignore
        except Exception:
            _fail("YAML config requires PyYAML. Install with: pip install pyyaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    _fail("Config file must be .json or .yaml/.yml")
    return {}


def _collect_brand_soul_chunks(session_factory, shop_domain: str) -> list[str]:
    db = session_factory()
    try:
        rows = db.query(StoreContext).filter(StoreContext.shop_id == shop_domain).all()
        return [r.content for r in rows]
    finally:
        db.close()


def _run_configured_brand_soul_cases() -> None:
    """
    Purpose: Run multiple Brand Soul cases defined in a JSON/YAML config.
    Why: Enables scalable local RAG coverage with real OpenAI calls.
    Expected output: Each product output includes required keywords from the brand soul.
    """
    _log("🧭 Purpose: Config-driven Brand Soul cases (multi-shop, multi-product)")
    _log("✅ Expected: Output includes required keywords per case")

    config = _load_cases_config(RAG_CASES_PATH)
    shops = config.get("shops") or []
    if not isinstance(shops, list) or not shops:
        _fail("Config 'shops' must be a non-empty list")

    _, SessionLocal = _get_db()
    results_summary: list[dict[str, Any]] = []

    with httpx.Client(base_url=API_BASE, timeout=120.0) as client:
        for shop_cfg in shops:
            shop_domain = str(shop_cfg.get("shop_domain") or "").strip()
            if not shop_domain:
                _fail("shop_domain is required for each shop config")
            headers = _auth_headers(shop_domain)
            _ensure_plan_user_shop(SessionLocal, shop_domain)

            brand_persona = shop_cfg.get("brand_persona")
            core_pillars = shop_cfg.get("core_pillars") or []
            raw_text = shop_cfg.get("raw_text")
            if not raw_text:
                _fail(f"raw_text is required for shop {shop_domain}")

            _log(f"🚀 Ingesting Brand Soul for {shop_domain}")
            resp = client.post(
                "/api/onboarding/brand-soul",
                json={
                    "brand_persona": brand_persona,
                    "core_pillars": core_pillars,
                    "raw_text": raw_text,
                },
                headers=headers,
            )
            if resp.status_code != 200:
                _fail(f"POST /api/onboarding/brand-soul failed: {resp.status_code} {resp.text}")
            data = resp.json()
            if data.get("status") != "accepted":
                _fail(f"Unexpected response: {data}")
            _poll_brand_context_ready(client, shop_domain, headers)

            chunks = _collect_brand_soul_chunks(SessionLocal, shop_domain)
            if not chunks:
                _fail(f"No store_context rows found for shop {shop_domain}")

            products = shop_cfg.get("products") or []
            if not isinstance(products, list) or not products:
                _fail(f"products list required for shop {shop_domain}")

            shop_expected = shop_cfg.get("expected_keywords") or []
            shop_min_hits = int(shop_cfg.get("min_expected_hits") or 1)

            for product_cfg in products:
                product_name = str(product_cfg.get("product_name") or "").strip()
                product_desc = str(product_cfg.get("japanese_description") or "").strip()
                category = str(product_cfg.get("category") or "Tableware").strip()
                if not product_name or not product_desc:
                    _fail(f"Product fields missing for shop {shop_domain}")

                expected_keywords = product_cfg.get("expected_keywords") or shop_expected
                min_hits = int(product_cfg.get("min_expected_hits") or shop_min_hits)

                _log(f"🚀 Generating copy for {shop_domain} | {product_name}")
                resp = client.post(
                    "/api/proxy/generate-bulk",
                    json={
                        "product_name": product_name,
                        "japanese_description": product_desc,
                        "category": category,
                        "target_locales": ["en"],
                        "brand_soul_enabled": True,
                    },
                    headers=headers,
                )
                if resp.status_code != 200:
                    _fail(f"POST /api/proxy/generate-bulk failed: {resp.status_code} {resp.text}")
                data = resp.json()
                if data.get("status") != "success":
                    _fail(f"Unexpected response: {data}")

                result = data.get("results", {}).get("en") or {}
                title = str(result.get("title") or "")
                description = str(result.get("description") or "")
                seo_title = str(result.get("seo_title") or "")
                seo_desc = str(result.get("seo_description") or "")
                haystack = " ".join([title, description, seo_title, seo_desc]).lower()

                found_keywords: list[str] = []
                for kw in expected_keywords:
                    if str(kw).lower() in haystack:
                        found_keywords.append(str(kw))
                passed = len(found_keywords) >= min_hits

                results_summary.append(
                    {
                        "shop_domain": shop_domain,
                        "product_name": product_name,
                        "passed": passed,
                        "expected_keywords": expected_keywords,
                        "found_keywords": found_keywords,
                        "min_hits": min_hits,
                        "brand_soul_chunks": chunks,
                        "title": title,
                        "description": description,
                    }
                )

                if not passed:
                    _fail(
                        f"Missing required keywords for {shop_domain} | {product_name} "
                        f"(found {found_keywords}, expected {expected_keywords}, min_hits={min_hits})"
                    )

    _log("✅ All config-driven Brand Soul cases passed")
    _print_summary(results_summary)


def _print_summary(summary_rows: list[dict[str, Any]]) -> None:
    _log("\n==== RAG LOCAL SUMMARY ====")
    for row in summary_rows:
        _log(f"Case: {row.get('shop_domain')} | {row.get('product_name')}")
        _log(f"Pass: {row.get('passed')}")
        _log("Brand Soul (vector DB):")
        for idx, chunk in enumerate(row.get("brand_soul_chunks") or [], start=1):
            _log(f"  [{idx}] {chunk}")
        _log("Title (raw):")
        _log(f"{row.get('title')}")
        _log("Description (raw):")
        _log(f"{row.get('description')}")
        _log(f"Expected keywords: {row.get('expected_keywords')}")
        _log(f"Found keywords: {row.get('found_keywords')}")
        _log("----")


def _run_test(name: str, fn: Callable[[], None]) -> bool:
    try:
        fn()
        return True
    except SystemExit as exc:
        _log(f"❌ {name} failed (exit code {exc.code})")
        return False
    except Exception as exc:
        _log(f"❌ {name} error: {exc}")
        return False


def main() -> None:
    _log("🚦 Running local RAG test suite")
    _ensure_env()
    tests: list[tuple[str, Callable[[], None]]] = [
        ("Onboarding -> Ingestion", test_onboarding_to_ingestion),
        ("Rewriter RAG Injection", test_rewriter_rag_injection),
        ("Multi-tenant Wall", test_multi_tenant_wall),
        ("Brand Soul About Us (JP)", test_brand_soul_about_us_case),
        ("Config-driven Brand Soul Cases", _run_configured_brand_soul_cases),
    ]
    passed = 0
    failed = 0
    for idx, (name, fn) in enumerate(tests):
        ok = _run_test(name, fn)
        if ok:
            passed += 1
        else:
            failed += 1
        if idx < len(tests) - 1:
            print("\n")

    _log(f"✅ Local RAG Summary: {passed} passed | ❌ {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

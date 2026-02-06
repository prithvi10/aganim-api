"""
Live local-dev backend test runner (black-box HTTP).

Goals:
- Exercise Basic / Standard / Pro feature gating end-to-end
- Use REAL OpenAI + REAL SERP + REAL Shopify writes (no mocks)
- Surface corner cases and bugs with stable, contract-focused assertions

Run (example):
  API_BASE_URL=http://localhost:8000 \
  DATABASE_URL=postgresql://postgres:postgres@localhost:5432/shopify_translator \
  OPENAI_API_KEY=sk-... \
  SERP_API_KEY=... \
  SHOPIFY_API_SECRET=... \
  TEST_SHOP_DOMAIN=your-dev-shop.myshopify.com \
  TEST_SHOP_ACCESS_TOKEN=shpat_... \
  TEST_PRODUCT_ID=1234567890 \
  python scripts/live_dev_tests.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import hmac
import hashlib

import httpx
from urllib.parse import urlencode

# Ensure repo root is on sys.path so `import src.*` works when running as a script.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Env loading (before importing app modules)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore

    # Load local .env if present (docker-compose already uses it; this allows CLI runs too)
    load_dotenv()
except Exception:
    # dotenv is optional; env may already be exported
    pass

# ---------------------------------------------------------------------------
# Project imports (DATABASE_URL is read during module import)
# ---------------------------------------------------------------------------
from src.main.db.database import Base, SessionLocal, engine  # noqa: E402
from src.main.db.db_models import Plan, Shop, User  # noqa: E402
from src.main.db.db_transactions import get_plan_by_name  # noqa: E402


# ---------------------------------------------------------------------------
# Mini test framework
# ---------------------------------------------------------------------------
class TestFailure(Exception):
    pass


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _require_env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise TestFailure(f"Missing required env var: {name}")
    return v


def _opt_env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise TestFailure(msg)


def _assert_eq(a: Any, b: Any, msg: str) -> None:
    if a != b:
        raise TestFailure(f"{msg} (got={a!r} expected={b!r})")


def _assert_in(sub: str, s: str, msg: str) -> None:
    if sub not in s:
        raise TestFailure(msg)


def _ts_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_json(obj: Any) -> Any:
    """
    Best-effort JSON-serializable conversion for report output.
    """
    try:
        json.dumps(obj)
        return obj
    except Exception:
        try:
            return str(obj)
        except Exception:
            return "<unserializable>"


@dataclass
class TestOutcome:
    name: str
    expected: str
    actual: Any
    status: str  # SUCCESS | FAILED | NOT_EXECUTED
    error: str | None = None


def _write_report_files(outcomes: list[TestOutcome], *, json_path: str, md_path: str) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "SUCCESS": sum(1 for o in outcomes if o.status == "SUCCESS"),
            "FAILED": sum(1 for o in outcomes if o.status == "FAILED"),
            "NOT_EXECUTED": sum(1 for o in outcomes if o.status == "NOT_EXECUTED"),
            "total": len(outcomes),
        },
        "tests": [
            {
                "name": o.name,
                "expected": o.expected,
                "actual": _safe_json(o.actual),
                "status": o.status,
                "error": o.error,
            }
            for o in outcomes
        ],
    }

    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    def _md_escape(s: str) -> str:
        return (s or "").replace("\n", " ").replace("|", "\\|").strip()

    lines: list[str] = []
    lines.append("## Live Dev Test Report")
    lines.append("")
    lines.append(f"- generated_at: `{payload['generated_at']}`")
    lines.append(
        f"- summary: SUCCESS={payload['summary']['SUCCESS']} "
        f"FAILED={payload['summary']['FAILED']} "
        f"NOT_EXECUTED={payload['summary']['NOT_EXECUTED']} "
        f"total={payload['summary']['total']}"
    )
    lines.append("")
    lines.append("| test_case | expected | actual | status | error |")
    lines.append("|---|---|---|---|---|")
    for o in outcomes:
        try:
            actual_str = json.dumps(_safe_json(o.actual), ensure_ascii=False)
        except Exception:
            actual_str = str(_safe_json(o.actual))
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_escape(o.name),
                    _md_escape(o.expected),
                    _md_escape(actual_str),
                    _md_escape(o.status),
                    _md_escape(o.error or ""),
                ]
            )
            + " |"
        )

    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


@dataclass(frozen=True)
class RunConfig:
    api_base_url: str
    shop_domain: str
    shop_access_token: str
    product_id: str
    shopify_api_secret: str
    shopify_api_version: str

    serp_api_key: str
    openai_api_key: str

    # Execution flags
    skip_openai: bool
    skip_serp: bool
    skip_shopify: bool
    full: bool
    no_restore: bool

    timeout_s: float
    insecure_ssl: bool


def _httpx_verify(cfg: RunConfig):
    """
    Return a `verify` value for httpx clients.
    - Prefer truststore (system/corporate certs) when available.
    - Allow explicit insecure mode for constrained environments.
    """
    if getattr(cfg, "insecure_ssl", False):
        return False
    try:
        import truststore  # type: ignore

        # Use system/corporate trust roots (works behind SSL-intercepting proxies)
        return truststore.SSLContext(httpx.create_ssl_context().protocol)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# DB helpers (switch plan tiers / manipulate quotas)
# ---------------------------------------------------------------------------
def _db_ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)


def _db_seed_plans() -> None:
    """
    Uses the existing seed script to ensure Plan rows are present and correct.
    """
    # Import locally to avoid side effects at module import time
    from scripts.seed_db import seed_data  # type: ignore

    seed_data()


def _db_get_or_create_user_shop(db, shop_domain: str, access_token: str) -> tuple[User, Shop]:
    user = db.query(User).filter(User.username == shop_domain).first()
    if not user:
        free = db.query(Plan).filter(Plan.name == "Free").first()
        if not free:
            raise TestFailure("Plan 'Free' not found in DB; seed failed?")
        user = User(username=shop_domain, email=None, plan_id=free.id)
        db.add(user)
        db.commit()
        db.refresh(user)

    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        now = _now_utc()
        shop = Shop(
            domain=shop_domain,
            access_token=access_token or "",
            monthly_rewrites_used=0,
            lifetime_rewrites_remaining=10,
            is_active=True,
            current_plan_name="Free",
            last_plan_name="Free",
            reset_anchor_date=now,
            next_reset_date=now + timedelta(days=30),
        )
        db.add(shop)
        db.commit()
        db.refresh(shop)
    else:
        # Keep token up to date for live Shopify tests.
        # NOTE: allow empty string to intentionally clear the token in negative tests.
        shop.access_token = access_token
        shop.is_active = True
        db.add(shop)
        db.commit()
        db.refresh(shop)

    return user, shop


def _db_set_plan(db, shop_domain: str, plan_name: str, *, access_token: str) -> None:
    plan = get_plan_by_name(db, plan_name)
    if not plan:
        raise TestFailure(f"Plan not found: {plan_name!r}. Did seed_db run?")

    user, shop = _db_get_or_create_user_shop(db, shop_domain, access_token)
    user.plan_id = plan.id

    # DB is source-of-truth for gating: set both current + last to be explicit
    shop.current_plan_name = plan.name
    shop.last_plan_name = plan.name
    shop.last_uninstalled_at = None
    shop.access_expires_at = None
    shop.pending_plan_name = None
    shop.pending_plan_effective_at = None

    # Set/reset cycle anchors for predictable quota tests
    now = _now_utc()
    shop.reset_anchor_date = now
    shop.next_reset_date = now + timedelta(days=30)

    # For paid plans, ensure access_expires_at exists so get_shop_quota_context does NOT
    # treat them as "expired_paid" (that logic considers missing access_expires_at expired).
    if str(plan.name or "").strip().lower() in ("basic", "standard", "pro"):
        shop.access_expires_at = now + timedelta(days=30)
    else:
        shop.access_expires_at = None

    # Reset usage counters (tests should set them explicitly when needed)
    shop.monthly_rewrites_used = 0
    if str(plan.billing_cycle_type or "").strip().lower() == "lifetime":
        shop.lifetime_rewrites_remaining = 10

    db.add_all([user, shop])
    db.commit()


def _db_set_monthly_used(db, shop_domain: str, used: int) -> None:
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        raise TestFailure("Shop row missing")
    shop.monthly_rewrites_used = int(used)
    db.add(shop)
    db.commit()


def _db_get_monthly_used(db, shop_domain: str) -> int:
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not shop:
        raise TestFailure("Shop row missing")
    return int(shop.monthly_rewrites_used or 0)


def _db_set_expired_paid(db, shop_domain: str, last_paid_plan_name: str) -> None:
    """
    Force 'expired paid' state:
    - last_plan_name=paid plan
    - access_expires_at in the past
    - last_uninstalled_at optional (not required for expired)
    """
    user = db.query(User).filter(User.username == shop_domain).first()
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not user or not shop:
        raise TestFailure("User/Shop row missing")
    # Put user on Free so we validate the override logic is actually being used
    free = db.query(Plan).filter(Plan.name == "Free").first()
    if not free:
        raise TestFailure("Plan 'Free' not found")
    user.plan_id = free.id

    shop.last_plan_name = last_paid_plan_name
    shop.current_plan_name = None
    shop.access_expires_at = _now_utc() - timedelta(days=1)
    shop.last_uninstalled_at = _now_utc() - timedelta(days=2)

    db.add_all([user, shop])
    db.commit()


def _db_set_grace_active(db, shop_domain: str, last_paid_plan_name: str) -> None:
    """
    Force 'grace active' state:
    - last_plan_name=paid plan
    - access_expires_at in the future
    - last_uninstalled_at set (so grace_mode=True)
    - user plan can be Free; gating should treat as last paid plan
    """
    user = db.query(User).filter(User.username == shop_domain).first()
    shop = db.query(Shop).filter(Shop.domain == shop_domain).first()
    if not user or not shop:
        raise TestFailure("User/Shop row missing")
    free = db.query(Plan).filter(Plan.name == "Free").first()
    if not free:
        raise TestFailure("Plan 'Free' not found")
    user.plan_id = free.id

    shop.last_plan_name = last_paid_plan_name
    shop.current_plan_name = None
    shop.access_expires_at = _now_utc() + timedelta(days=7)
    shop.last_uninstalled_at = _now_utc() - timedelta(hours=1)

    db.add_all([user, shop])
    db.commit()


# ---------------------------------------------------------------------------
# Shopify helpers (GraphQL)
# ---------------------------------------------------------------------------
def _shopify_graphql(
    cfg: RunConfig,
    *,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"https://{cfg.shop_domain}/admin/api/{cfg.shopify_api_version}/graphql.json"
    headers = {"X-Shopify-Access-Token": cfg.shop_access_token, "Content-Type": "application/json"}
    with httpx.Client(timeout=cfg.timeout_s, verify=_httpx_verify(cfg)) as client:
        resp = client.post(url, headers=headers, json={"query": query, "variables": variables or {}})
        if resp.status_code != 200:
            raise TestFailure(f"Shopify GraphQL non-200: {resp.status_code} body={resp.text[:500]}")
        data = resp.json() or {}
        if "errors" in data and data["errors"]:
            raise TestFailure(f"Shopify GraphQL errors: {json.dumps(data['errors'])[:800]}")
        return data.get("data") or {}


def _shopify_product_gid(product_id: str) -> str:
    pid = str(product_id).strip()
    return f"gid://shopify/Product/{pid}"


def _shopify_get_shop_locales(cfg: RunConfig) -> dict[str, Any]:
    q = """
    {
      shopLocales {
        locale
        name
        primary
        published
      }
    }
    """
    data = _shopify_graphql(cfg, query=q)
    locales = data.get("shopLocales") or []
    primary = None
    published = []
    for l in locales:
        if l.get("primary"):
            primary = l.get("locale")
        if l.get("published"):
            published.append(l.get("locale"))
    return {"locales": locales, "primary_locale": primary, "published_locales": published}


def _shopify_get_product_primary_content(cfg: RunConfig, product_id: str) -> dict[str, str]:
    q = """
    query ($id: ID!) {
      product(id: $id) {
        title
        descriptionHtml
      }
    }
    """
    data = _shopify_graphql(cfg, query=q, variables={"id": _shopify_product_gid(product_id)})
    prod = data.get("product") or {}
    return {"title": str(prod.get("title") or ""), "descriptionHtml": str(prod.get("descriptionHtml") or "")}


def _shopify_try_get_translations(cfg: RunConfig, product_id: str, locale: str) -> dict[str, str] | None:
    """
    Best-effort: fetch translation values for title/body_html.
    Shopify schema varies by API version; if unsupported, return None (caller may warn/skip).
    """
    q = """
    query ($resourceId: ID!, $locale: String!) {
      translatableResource(resourceId: $resourceId) {
        translations(locale: $locale) {
          key
          value
          locale
        }
      }
    }
    """
    try:
        data = _shopify_graphql(cfg, query=q, variables={"resourceId": _shopify_product_gid(product_id), "locale": locale})
        tr = (data.get("translatableResource") or {}).get("translations") or []
        out: dict[str, str] = {}
        for item in tr:
            k = str(item.get("key") or "").strip()
            v = str(item.get("value") or "")
            if k:
                out[k] = v
        return out or None
    except Exception:
        return None


def _shopify_product_update(cfg: RunConfig, product_id: str, *, title: str, description_html: str) -> None:
    m = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id title descriptionHtml }
        userErrors { field message }
      }
    }
    """
    variables = {
        "input": {
            "id": _shopify_product_gid(product_id),
            "title": title,
            "descriptionHtml": description_html,
        }
    }
    data = _shopify_graphql(cfg, query=m, variables=variables)
    errs = ((data.get("productUpdate") or {}).get("userErrors")) or []
    if errs:
        raise TestFailure(f"Shopify productUpdate userErrors: {json.dumps(errs)[:800]}")


def _shopify_translations_register(cfg: RunConfig, product_id: str, *, locale: str, title: str, body_html: str) -> None:
    """
    Register translations using digests, matching the backend behavior.
    """
    digest_q = """
    query getTranslatableContent($resourceId: ID!) {
      translatableResource(resourceId: $resourceId) {
        translatableContent {
          key
          digest
        }
      }
    }
    """
    res_id = _shopify_product_gid(product_id)
    d = _shopify_graphql(cfg, query=digest_q, variables={"resourceId": res_id})
    contents = ((d.get("translatableResource") or {}).get("translatableContent")) or []
    title_digest = ""
    body_digest = ""
    for item in contents:
        if item.get("key") == "title":
            title_digest = str(item.get("digest") or "")
        if item.get("key") == "body_html":
            body_digest = str(item.get("digest") or "")
    if not title_digest or not body_digest:
        raise TestFailure("Unable to fetch digests for title/body_html; cannot translationsRegister")

    m = """
    mutation translationsRegister($resourceId: ID!, $translations: [TranslationInput!]!) {
      translationsRegister(resourceId: $resourceId, translations: $translations) {
        userErrors { message field }
      }
    }
    """
    variables = {
        "resourceId": res_id,
        "translations": [
            {"locale": locale, "key": "title", "value": title, "translatableContentDigest": title_digest},
            {"locale": locale, "key": "body_html", "value": body_html, "translatableContentDigest": body_digest},
        ],
    }
    data = _shopify_graphql(cfg, query=m, variables=variables)
    errs = ((data.get("translationsRegister") or {}).get("userErrors")) or []
    if errs:
        raise TestFailure(f"Shopify translationsRegister userErrors: {json.dumps(errs)[:800]}")


@dataclass
class ShopifySnapshot:
    primary_title: str
    primary_description_html: str
    translations_by_locale: dict[str, dict[str, str]]  # locale -> {key:value}


def _shopify_snapshot(cfg: RunConfig, product_id: str, *, locales: Iterable[str]) -> ShopifySnapshot:
    primary = _shopify_get_product_primary_content(cfg, product_id)
    translations_by_locale: dict[str, dict[str, str]] = {}
    for loc in locales:
        tr = _shopify_try_get_translations(cfg, product_id, loc)
        if tr:
            translations_by_locale[str(loc)] = tr
    return ShopifySnapshot(
        primary_title=primary["title"],
        primary_description_html=primary["descriptionHtml"],
        translations_by_locale=translations_by_locale,
    )


def _shopify_restore(cfg: RunConfig, product_id: str, snap: ShopifySnapshot) -> None:
    # Restore primary
    _shopify_product_update(cfg, product_id, title=snap.primary_title, description_html=snap.primary_description_html)
    # Restore translations if we could snapshot them
    for loc, tr in (snap.translations_by_locale or {}).items():
        title = str(tr.get("title") or "")
        body = str(tr.get("body_html") or tr.get("descriptionHtml") or "")
        if title or body:
            _shopify_translations_register(cfg, product_id, locale=loc, title=title, body_html=body)


# ---------------------------------------------------------------------------
# Proxy signature helper
# ---------------------------------------------------------------------------
def _proxy_signed_params(cfg: RunConfig, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    """
    Generate query params that satisfy verify_shopify_proxy_request().
    Server accepts several canonicalizations; we use the urlencode(sorted)->remove('&') variant.
    """
    params: dict[str, str] = {
        "shop": cfg.shop_domain,
        "timestamp": str(int(time.time())),
        "path_prefix": "/apps/proxy",
    }
    if extra:
        for k, v in extra.items():
            if v is None:
                continue
            params[str(k)] = str(v)
    # Canonical string MUST match server cand[D]:
    # urllib.parse.urlencode(sorted(decoded_items)).replace("&","")
    items = sorted(params.items(), key=lambda kv: (kv[0], kv[1]))
    cand = urlencode(items).replace("&", "")
    sig = hmac.new(cfg.shopify_api_secret.encode("utf-8"), cand.encode("utf-8"), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


# ---------------------------------------------------------------------------
# Backend HTTP helpers
# ---------------------------------------------------------------------------
def _api_url(cfg: RunConfig, path: str) -> str:
    return cfg.api_base_url.rstrip("/") + path


def _post_json(cfg: RunConfig, path: str, *, params: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> httpx.Response:
    with httpx.Client(timeout=cfg.timeout_s, verify=_httpx_verify(cfg)) as client:
        return client.post(_api_url(cfg, path), params=params, json=body or {})


def _get(cfg: RunConfig, path: str, *, params: dict[str, str] | None = None) -> httpx.Response:
    with httpx.Client(timeout=cfg.timeout_s, verify=_httpx_verify(cfg)) as client:
        return client.get(_api_url(cfg, path), params=params)


def _stream_post(cfg: RunConfig, path: str, *, params: dict[str, str], body: dict[str, Any]) -> str:
    with httpx.Client(timeout=cfg.timeout_s, verify=_httpx_verify(cfg)) as client:
        with client.stream("POST", _api_url(cfg, path), params=params, json=body) as resp:
            if resp.status_code != 200:
                # In streaming mode, resp.text/content require reading first.
                try:
                    raw = resp.read()
                    txt = raw.decode("utf-8", errors="replace")
                except Exception:
                    txt = "<unable_to_read_body>"
                raise TestFailure(f"Expected 200 stream, got {resp.status_code}: {txt[:300]}")
            chunks: list[str] = []
            for txt in resp.iter_text():
                if txt:
                    chunks.append(txt)
            return "".join(chunks)


# ---------------------------------------------------------------------------
# Stable output assertions (LLM variability-tolerant)
# ---------------------------------------------------------------------------
def _assert_copy_contract(payload: dict[str, Any]) -> None:
    _assert(payload.get("status") == "success", f"Expected status=success, got {payload.get('status')!r}")
    data = payload.get("data")
    _assert(isinstance(data, dict), "Response missing data dict")
    for k in ("title", "description", "seo_title", "seo_description", "seo_alt_text"):
        _assert(k in data, f"Missing key in data: {k}")
        _assert(isinstance(data.get(k), str), f"data.{k} must be a string")

    seo_title = data.get("seo_title") or ""
    seo_desc = data.get("seo_description") or ""
    _assert(len(seo_title) <= 70, f"seo_title too long: {len(seo_title)}")
    _assert(len(seo_desc) <= 160, f"seo_description too long: {len(seo_desc)}")

    desc = data.get("description") or ""
    # Check for spec tables (Standard/Pro tiers generate separate tables)
    has_specs = "<h3>Product Specifications</h3>" in desc
    has_dims = "<h3>Detailed Dimensions</h3>" in desc
    _assert(has_specs or has_dims, "Missing mandatory spec tables (Product Specifications or Detailed Dimensions) in description")


def _assert_competitor_results_present(payload: dict[str, Any]) -> None:
    data = payload.get("data") or {}
    comp = data.get("competitor_results")
    _assert(isinstance(comp, list), "Expected competitor_results list")
    _assert(len(comp) > 0, "Expected competitor_results non-empty (SERP enrichment missing?)")


def _assert_unit_conversion_happened(payload: dict[str, Any], *, metric_token: str = "10 cm") -> None:
    desc = (payload.get("data") or {}).get("description") or ""
    _assert(metric_token in desc, f"Expected metric token preserved in description: {metric_token!r}")
    # Look for something like "10 cm (3.9 in)" somewhere after it
    idx = desc.find(metric_token)
    window = desc[idx : idx + 1200] if idx >= 0 else desc
    _assert(re.search(r"\(\s*approx\.\s*\d", window, re.IGNORECASE) or re.search(r"\(\s*\d", window), "Expected parenthetical US-unit conversion near metric value")


# ---------------------------------------------------------------------------
# Individual tests
# ---------------------------------------------------------------------------
def test_validation_invalid_json(cfg: RunConfig) -> dict[str, Any]:
    # Send invalid JSON (raw body)
    params = {"shop": cfg.shop_domain}
    with httpx.Client(timeout=cfg.timeout_s, verify=_httpx_verify(cfg)) as client:
        resp = client.post(_api_url(cfg, "/api/proxy/generate-copy"), params=params, content=b"{not-json")
    _assert_eq(resp.status_code, 400, "Invalid JSON should return 400")
    return {"status_code": resp.status_code}


def test_validation_missing_shop_param(cfg: RunConfig) -> dict[str, Any]:
    resp = _post_json(cfg, "/api/proxy/generate-copy", params={}, body={"product_name": "P", "japanese_description": "x", "category": "General"})
    _assert_eq(resp.status_code, 400, "Missing shop param should return 400")
    return {"status_code": resp.status_code}


def test_validation_empty_description(cfg: RunConfig) -> dict[str, Any]:
    params = {"shop": cfg.shop_domain}
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body={"product_name": "P", "japanese_description": "   ", "category": "General"})
    _assert_eq(resp.status_code, 422, "Empty description should return 422")
    return {"status_code": resp.status_code}


def test_validation_too_long_description(cfg: RunConfig) -> dict[str, Any]:
    params = {"shop": cfg.shop_domain}
    too_long = "あ" * 5001
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body={"product_name": "P", "japanese_description": too_long, "category": "General"})
    _assert_eq(resp.status_code, 422, "Too-long description should return 422")
    return {"status_code": resp.status_code}


def test_validation_invalid_tone_profile(cfg: RunConfig) -> dict[str, Any]:
    params = {"shop": cfg.shop_domain}
    resp = _post_json(
        cfg,
        "/api/proxy/generate-copy",
        params=params,
        body={"product_name": "P", "japanese_description": "黒い革の財布。", "category": "General", "tone_profile": "angry"},
    )
    _assert_eq(resp.status_code, 422, "Invalid tone_profile should return 422 (pydantic enum)")
    return {"status_code": resp.status_code}


def test_proxy_locales_signature(cfg: RunConfig) -> dict[str, Any]:
    params = _proxy_signed_params(cfg)
    resp = _get(cfg, "/api/proxy/shop/locales", params=params)
    _assert_eq(resp.status_code, 200, "Valid proxy signature should succeed")
    data = resp.json()
    _assert(data.get("status") == "success", "Locales endpoint must return status=success")
    _assert(isinstance(data.get("locales"), list), "Locales endpoint must return locales list")
    return {"status_code": resp.status_code, "locales_count": len(data.get("locales") or [])}


def test_proxy_locales_missing_signature(cfg: RunConfig) -> dict[str, Any]:
    resp = _get(cfg, "/api/proxy/shop/locales", params={"shop": cfg.shop_domain})
    _assert(resp.status_code in (400, 401), "Missing signature should be 400/401")
    return {"status_code": resp.status_code}


def test_basic_streaming_forbidden(cfg: RunConfig) -> dict[str, Any]:
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Basic", access_token=cfg.shop_access_token)
    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "Leather Wallet",
        "japanese_description": "黒い革の財布。サイズ: 10 cm x 2 cm。日本製。",
        "category": "Accessories",
        "stream": True,
        "target_locale": "en",
    }
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert_eq(resp.status_code, 403, "Basic streaming must be forbidden (403)")
    return {"status_code": resp.status_code}


def test_standard_streaming_forbidden(cfg: RunConfig) -> dict[str, Any]:
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Standard", access_token=cfg.shop_access_token)
    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "Leather Wallet",
        "japanese_description": "黒い革の財布。サイズ: 10 cm x 2 cm。日本製。",
        "category": "Accessories",
        "stream": True,
        "target_locale": "en",
    }
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert_eq(resp.status_code, 403, "Standard streaming must be forbidden (403)")
    return {"status_code": resp.status_code}


def test_pro_streaming_success_and_usage_increments(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run streaming test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Pro", access_token=cfg.shop_access_token)
        before = _db_get_monthly_used(db, cfg.shop_domain)
    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "Leather Wallet",
        "japanese_description": "黒い革の財布。サイズ: 10 cm x 2 cm。日本製。",
        "category": "Accessories",
        "stream": True,
        "target_locale": "en",
    }
    txt = _stream_post(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert(len(txt.strip()) > 0, "Streaming response should contain content")
    # usage increment happens after stream completes
    with SessionLocal() as db:
        after = _db_get_monthly_used(db, cfg.shop_domain)
    _assert_eq(after, before + 1, "Pro streaming should increment monthly_rewrites_used by 1")
    return {"stream_text_len": len(txt), "monthly_rewrites_used_before": before, "monthly_rewrites_used_after": after}


def test_standard_generate_copy_contract_and_serp(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run generate-copy test")
    if not cfg.skip_serp:
        _assert(cfg.serp_api_key, "SERP_API_KEY required for this run (or set --skip-serp)")

    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Standard", access_token=cfg.shop_access_token)

    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "Kyoto Matcha Bowl",
        "japanese_description": "京都の職人が作る抹茶碗。サイズ: 10 cm。手作り。日本製。",
        "category": "Home & Kitchen",
        "stream": False,
        "target_locale": "en",
        "auto_convert_units": True,
        "tone_profile": "luxury",
    }
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert_eq(resp.status_code, 200, "Standard generate-copy should succeed")
    payload = resp.json()
    _assert_copy_contract(payload)
    _assert_unit_conversion_happened(payload, metric_token="10 cm")
    if not cfg.skip_serp:
        _assert_competitor_results_present(payload)
    comp = (payload.get("data") or {}).get("competitor_results") or []
    return {"status_code": resp.status_code, "competitor_results_count": len(comp) if isinstance(comp, list) else None}


def test_basic_generate_copy_no_serp(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run generate-copy test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Basic", access_token=cfg.shop_access_token)
    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "Simple Mug",
        "japanese_description": "白いマグカップ。容量: 300 ml。サイズ: 10 cm。日本製。",
        "category": "Kitchenware",
        "stream": False,
        "target_locale": "en",
        # Basic should force professional even if requested playful
        "tone_profile": "playful",
        "auto_convert_units": True,
    }
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert_eq(resp.status_code, 200, "Basic generate-copy should succeed")
    payload = resp.json()
    _assert_copy_contract(payload)
    # Basic should not include competitor_results (or empty) since it doesn't fetch SERP
    data = payload.get("data") or {}
    comp = data.get("competitor_results")
    if comp is not None:
        _assert(isinstance(comp, list), "competitor_results must be list if present")
        _assert(len(comp) == 0, "Basic competitor_results should be empty if present")
    return {"status_code": resp.status_code, "competitor_results_present": comp is not None, "competitor_results_count": len(comp) if isinstance(comp, list) else None}


def test_bulk_basic_multilocale_forbidden(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run bulk test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Basic", access_token=cfg.shop_access_token)
    params = _proxy_signed_params(cfg)
    body = {
        "product_name": "Tea Set",
        "japanese_description": "急須と茶碗のセット。サイズ: 10 cm。日本製。",
        "category": "Kitchenware",
        "product_id": None,
        "target_locales": ["en", "fr"],
        "auto_convert_units": True,
    }
    resp = _post_json(cfg, "/api/proxy/generate-bulk", params=params, body=body)
    _assert_eq(resp.status_code, 403, "Basic bulk multi-locale must be forbidden (403)")
    return {"status_code": resp.status_code}


def test_bulk_standard_two_locales(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run bulk test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Standard", access_token=cfg.shop_access_token)
    params = _proxy_signed_params(cfg)
    body = {
        "product_name": "Tea Set",
        "japanese_description": "急須と茶碗のセット。サイズ: 10 cm。日本製。",
        "category": "Kitchenware",
        "product_id": None,
        "target_locales": ["en", "fr"],
        "auto_convert_units": True,
        "tone_profile": "minimalist",
    }
    resp = _post_json(cfg, "/api/proxy/generate-bulk", params=params, body=body)
    _assert_eq(resp.status_code, 200, "Standard bulk should succeed")
    payload = resp.json()
    _assert(payload.get("status") == "success", "Bulk response must be success")
    results = payload.get("results")
    _assert(isinstance(results, dict), "Bulk results must be dict")
    _assert("en" in results and "fr" in results, "Bulk results must contain both locales")
    return {"status_code": resp.status_code, "results_locales": sorted(list(results.keys()))}


def test_bulk_pro_three_locales(cfg: RunConfig) -> dict[str, Any]:
    if not cfg.full:
        raise TestFailure("Skipped by default unless --full (expensive: 3 OpenAI generations)")
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run bulk test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Pro", access_token=cfg.shop_access_token)
    params = _proxy_signed_params(cfg)
    body = {
        "product_name": "Tea Set",
        "japanese_description": "急須と茶碗のセット。サイズ: 10 cm。日本製。",
        "category": "Kitchenware",
        "product_id": None,
        "target_locales": ["en", "fr", "ko"],
        "auto_convert_units": True,
        "tone_profile": "luxury",
    }
    resp = _post_json(cfg, "/api/proxy/generate-bulk", params=params, body=body)
    _assert_eq(resp.status_code, 200, "Pro bulk should succeed")
    payload = resp.json()
    _assert(payload.get("status") == "success", "Bulk response must be success")
    results = payload.get("results")
    _assert(isinstance(results, dict), "Bulk results must be dict")
    for loc in ("en", "fr", "ko"):
        _assert(loc in results, f"Missing locale in results: {loc}")
    return {"status_code": resp.status_code, "results_locales": sorted(list(results.keys()))}


def test_paid_grace_allows_pro_features(cfg: RunConfig) -> dict[str, Any]:
    """
    Corner case: user plan is Free, but last_plan_name=Pro and grace is active.
    Should permit Pro-only features like streaming.
    """
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run grace test")
    with SessionLocal() as db:
        _db_set_grace_active(db, cfg.shop_domain, "Pro")
    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "Leather Wallet",
        "japanese_description": "黒い革の財布。サイズ: 10 cm x 2 cm。日本製。",
        "category": "Accessories",
        "stream": True,
        "target_locale": "en",
    }
    # If grace override works, plan resolves to Pro, so streaming should be 200.
    txt = _stream_post(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert(len(txt.strip()) > 0, "Grace streaming response should contain content")
    return {"stream_text_len": len(txt)}


def test_paid_expired_blocks_generation(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run expired-paid test")
    with SessionLocal() as db:
        _db_set_expired_paid(db, cfg.shop_domain, "Pro")
    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "Leather Wallet",
        "japanese_description": "黒い革の財布。サイズ: 10 cm x 2 cm。日本製。",
        "category": "Accessories",
        "stream": False,
        "target_locale": "en",
    }
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert_eq(resp.status_code, 403, "Expired paid should block generation (403)")
    detail = ""
    try:
        detail = str((resp.json() or {}).get("detail") or "")
    except Exception:
        detail = resp.text
    _assert("pre-paid period" in detail.lower(), "Expired paid error message should mention pre-paid period ended")
    return {"status_code": resp.status_code, "detail_snippet": detail[:200]}


def test_shopify_missing_token_causes_500(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_shopify:
        raise TestFailure("skip_shopify=true; cannot run Shopify test")
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run Shopify writeback test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Standard", access_token="")  # clear token
    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "Test Product",
        "japanese_description": "テスト商品。サイズ: 10 cm。日本製。",
        "category": "General",
        "stream": False,
        "target_locale": "en",
        "product_id": int(cfg.product_id),
    }
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert_eq(resp.status_code, 500, "Missing Shopify access token should 500")
    return {"status_code": resp.status_code}


def test_shopify_primary_locale_writeback(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_shopify:
        raise TestFailure("skip_shopify=true; cannot run Shopify test")
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run Shopify writeback test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Standard", access_token=cfg.shop_access_token)
    # Determine primary locale (so we route to productUpdate)
    locales = _shopify_get_shop_locales(cfg)
    primary = locales.get("primary_locale") or "en"

    params = {"shop": cfg.shop_domain}
    body = {
        "product_name": "LiveDevTest Primary Update",
        "japanese_description": "テスト更新。サイズ: 10 cm。日本製。",
        "category": "General",
        "stream": False,
        "target_locale": primary,
        "product_id": int(cfg.product_id),
        "auto_convert_units": True,
    }
    resp = _post_json(cfg, "/api/proxy/generate-copy", params=params, body=body)
    _assert_eq(resp.status_code, 200, "Generate-copy with product_id should succeed")
    payload = resp.json()
    _assert_copy_contract(payload)

    # Readback: confirm product primary content changed (title contains our new title or AI title)
    prod = _shopify_get_product_primary_content(cfg, cfg.product_id)
    _assert(len(prod.get("title") or "") > 0, "Shopify readback missing title")
    return {"status_code": resp.status_code, "shop_primary_locale": primary, "shopify_readback_title_len": len(prod.get("title") or "")}


def test_shopify_secondary_locale_translation_via_bulk(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_shopify:
        raise TestFailure("skip_shopify=true; cannot run Shopify test")
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run Shopify translation test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Pro", access_token=cfg.shop_access_token)

    locales = _shopify_get_shop_locales(cfg)
    primary = str(locales.get("primary_locale") or "en")
    published = [str(x) for x in (locales.get("published_locales") or []) if str(x)]
    # Choose a secondary locale different from primary
    secondary = None
    for cand in ("fr", "ko", "zh-TW", "en"):
        if cand != primary and cand in published:
            secondary = cand
            break
    if not secondary:
        raise TestFailure(f"No suitable secondary published locale found. primary={primary} published={published}")

    params = _proxy_signed_params(cfg)
    body = {
        "product_name": "LiveDevTest Secondary Translation",
        "japanese_description": "翻訳テスト。サイズ: 10 cm。日本製。",
        "category": "General",
        "product_id": int(cfg.product_id),
        # IMPORTANT: include secondary then primary (backend already reorders to update primary last)
        "target_locales": [secondary, primary],
        "auto_convert_units": True,
        "tone_profile": "professional",
    }
    resp = _post_json(cfg, "/api/proxy/generate-bulk", params=params, body=body)
    _assert_eq(resp.status_code, 200, "Bulk translation should succeed")
    payload = resp.json()
    _assert(payload.get("status") == "success", "Bulk response must be success")
    results = payload.get("results") or {}
    _assert(secondary in results and primary in results, "Bulk results must include secondary+primary")

    # Best-effort readback for translation
    tr = _shopify_try_get_translations(cfg, cfg.product_id, secondary)
    _assert(tr is not None, "Unable to read back translations for secondary locale (schema/version mismatch?)")
    return {"status_code": resp.status_code, "primary_locale": primary, "secondary_locale": secondary, "translation_keys": sorted(list((tr or {}).keys()))}


def test_agent_social_hook_architect(cfg: RunConfig) -> dict[str, Any]:
    if cfg.skip_openai:
        raise TestFailure("skip_openai=true; cannot run agent test")
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Standard", access_token=cfg.shop_access_token)
    params = _proxy_signed_params(cfg)
    body = {
        "action": "social_hook_architect",
        "context": {"request_id": f"live-dev-{int(time.time())}"},
        "product_data": {"title": "Kyoto Matcha Bowl", "category": "Home & Kitchen", "tags": ["handmade", "Kyoto"]},
    }
    resp = _post_json(cfg, "/apps/cross-border/agent", params=params, body=body)
    _assert_eq(resp.status_code, 200, "Agent endpoint should succeed")
    payload = resp.json()
    _assert(payload.get("status") == "success", "Agent status must be success")
    data = payload.get("data") or {}
    _assert(isinstance(data.get("text"), str), "Agent data.text must be string")
    md = data.get("metadata") or {}
    hooks = md.get("hooks")
    _assert(isinstance(hooks, list) and len(hooks) == 3, "Expected 3 hooks in metadata.hooks")
    return {"status_code": resp.status_code, "hooks_count": len(hooks) if isinstance(hooks, list) else None}


def test_agent_unknown_action(cfg: RunConfig) -> dict[str, Any]:
    with SessionLocal() as db:
        _db_set_plan(db, cfg.shop_domain, "Standard", access_token=cfg.shop_access_token)
    params = _proxy_signed_params(cfg)
    body = {"action": "not_a_real_action", "context": {}, "product_data": {}}
    resp = _post_json(cfg, "/apps/cross-border/agent", params=params, body=body)
    _assert_eq(resp.status_code, 400, "Unknown agent action should be 400")
    return {"status_code": resp.status_code}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TestCase:
    name: str
    fn: Callable[[RunConfig], Any]
    expected: str
    requires_shopify_mutation: bool = False
    expensive: bool = False


def _build_tests() -> list[TestCase]:
    return [
        TestCase(
            "validation_invalid_json",
            test_validation_invalid_json,
            expected="POST /api/proxy/generate-copy with invalid JSON returns HTTP 400",
        ),
        TestCase(
            "validation_missing_shop_param",
            test_validation_missing_shop_param,
            expected="POST /api/proxy/generate-copy without shop query param returns HTTP 400",
        ),
        TestCase(
            "validation_empty_description",
            test_validation_empty_description,
            expected="Empty/whitespace japanese_description returns HTTP 422",
        ),
        TestCase(
            "validation_too_long_description",
            test_validation_too_long_description,
            expected="japanese_description > 5000 chars returns HTTP 422",
        ),
        TestCase(
            "validation_invalid_tone_profile",
            test_validation_invalid_tone_profile,
            expected="Invalid tone_profile (not in enum) returns HTTP 422",
        ),
        TestCase(
            "proxy_locales_signature",
            test_proxy_locales_signature,
            expected="GET /api/proxy/shop/locales with valid proxy signature returns HTTP 200 + locales list",
        ),
        TestCase(
            "proxy_locales_missing_signature",
            test_proxy_locales_missing_signature,
            expected="GET /api/proxy/shop/locales missing signature returns HTTP 400 or 401",
        ),
        TestCase(
            "basic_streaming_forbidden",
            test_basic_streaming_forbidden,
            expected="Basic plan: stream=true returns HTTP 403",
        ),
        TestCase(
            "standard_streaming_forbidden",
            test_standard_streaming_forbidden,
            expected="Standard plan: stream=true returns HTTP 403",
        ),
        TestCase(
            "pro_streaming_success_and_usage_increments",
            test_pro_streaming_success_and_usage_increments,
            expected="Pro plan: stream=true returns HTTP 200 stream, and monthly_rewrites_used increments by +1",
        ),
        TestCase(
            "standard_generate_copy_contract_and_serp",
            test_standard_generate_copy_contract_and_serp,
            expected="Standard plan: generate-copy succeeds, meets SEO+dimensions contract, and has competitor_results when SERP enabled",
        ),
        TestCase(
            "basic_generate_copy_no_serp",
            test_basic_generate_copy_no_serp,
            expected="Basic plan: generate-copy succeeds and does not include SERP competitor_results (or empty list)",
        ),
        TestCase(
            "bulk_basic_multilocale_forbidden",
            test_bulk_basic_multilocale_forbidden,
            expected="Basic plan: bulk with 2 locales returns HTTP 403",
        ),
        TestCase(
            "bulk_standard_two_locales",
            test_bulk_standard_two_locales,
            expected="Standard plan: bulk with 2 locales returns HTTP 200 and results contain both locales",
        ),
        TestCase(
            "bulk_pro_three_locales",
            test_bulk_pro_three_locales,
            expected="Pro plan: bulk with 3 locales returns HTTP 200 and results contain en/fr/ko (only in --full)",
            expensive=True,
        ),
        TestCase(
            "paid_grace_allows_pro_features",
            test_paid_grace_allows_pro_features,
            expected="Grace active with last paid=Pro: stream=true works (HTTP 200 stream)",
        ),
        TestCase(
            "paid_expired_blocks_generation",
            test_paid_expired_blocks_generation,
            expected="Expired paid window: generate-copy returns HTTP 403 with pre-paid ended message",
        ),
        TestCase(
            "agent_social_hook_architect",
            test_agent_social_hook_architect,
            expected="Agent social_hook_architect returns HTTP 200 and 3 hooks in metadata",
        ),
        TestCase(
            "agent_unknown_action",
            test_agent_unknown_action,
            expected="Unknown agent action returns HTTP 400",
        ),
        TestCase(
            "shopify_missing_token_causes_500",
            test_shopify_missing_token_causes_500,
            expected="When product_id is provided but DB shop token is empty, API returns HTTP 500",
            requires_shopify_mutation=False,
        ),
        TestCase(
            "shopify_primary_locale_writeback",
            test_shopify_primary_locale_writeback,
            expected="generate-copy with product_id updates primary locale via Shopify productUpdate and is readable back",
            requires_shopify_mutation=True,
        ),
        TestCase(
            "shopify_secondary_locale_translation_via_bulk",
            test_shopify_secondary_locale_translation_via_bulk,
            expected="bulk with [secondary, primary] registers translation for secondary via translationsRegister and is readable back",
            requires_shopify_mutation=True,
        ),
    ]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=_opt_env("API_BASE_URL", "http://localhost:8000"))
    p.add_argument("--timeout", type=float, default=float(_opt_env("LIVE_TEST_TIMEOUT_S", "90")))
    p.add_argument("--full", action="store_true", help="Run expensive tests (more OpenAI calls).")
    p.add_argument("--no-restore", action="store_true", help="Do not restore Shopify product state after mutation tests.")
    p.add_argument("--skip-openai", action="store_true", help="Skip tests that require OpenAI.")
    p.add_argument("--skip-serp", action="store_true", help="Skip SERP assertions/calls (Standard/Pro still works but competitor_results may be empty).")
    p.add_argument("--skip-shopify", action="store_true", help="Skip Shopify-mutation tests (productUpdate/translationsRegister).")
    p.add_argument("--insecure-ssl", action="store_true", help="Disable TLS certificate verification for outbound HTTP (Shopify/SERP). Not recommended.")
    p.add_argument("--report-json", default="", help="Write a JSON report to this path (default: logs/live_dev_test_report_<ts>.json).")
    p.add_argument("--report-md", default="", help="Write a Markdown report to this path (default: logs/live_dev_test_report_<ts>.md).")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    insecure = (
        bool(args.insecure_ssl)
        or _opt_env("LIVE_TEST_INSECURE_SSL", "").lower() in ("1", "true", "yes", "y", "on")
        or _opt_env("SHOPIFY_INSECURE_SSL", "").lower() in ("1", "true", "yes", "y", "on")
    )

    cfg = RunConfig(
        api_base_url=str(args.base_url).strip(),
        shop_domain=_require_env("TEST_SHOP_DOMAIN"),
        shop_access_token=_require_env("TEST_SHOP_ACCESS_TOKEN"),
        product_id=_require_env("TEST_PRODUCT_ID"),
        shopify_api_secret=_require_env("SHOPIFY_API_SECRET"),
        shopify_api_version=_opt_env("SHOPIFY_API_VERSION", "2024-07"),
        serp_api_key=_opt_env("SERP_API_KEY", ""),
        openai_api_key=_opt_env("OPENAI_API_KEY", ""),
        skip_openai=bool(args.skip_openai),
        skip_serp=bool(args.skip_serp),
        skip_shopify=bool(args.skip_shopify),
        full=bool(args.full),
        no_restore=bool(args.no_restore),
        timeout_s=float(args.timeout),
        insecure_ssl=bool(insecure),
    )

    if not cfg.skip_openai:
        _assert(cfg.openai_api_key, "OPENAI_API_KEY required (or pass --skip-openai)")
    if not cfg.skip_serp and not cfg.skip_openai:
        # SERP calls are only made for Standard/Pro; require key unless explicitly skipped.
        _assert(cfg.serp_api_key, "SERP_API_KEY required (or pass --skip-serp)")

    # DB init/seed
    _db_ensure_schema()
    _db_seed_plans()
    with SessionLocal() as db:
        _db_get_or_create_user_shop(db, cfg.shop_domain, cfg.shop_access_token)

    tests = _build_tests()
    outcomes: list[TestOutcome] = []

    # Snapshot Shopify state for mutation tests
    snap: ShopifySnapshot | None = None
    mutation_locales: list[str] = []
    if not cfg.skip_shopify:
        try:
            loc = _shopify_get_shop_locales(cfg)
            primary = str(loc.get("primary_locale") or "en")
            # Try to capture a likely secondary locale if present
            published = [str(x) for x in (loc.get("published_locales") or []) if str(x)]
            secondary = next((x for x in ("fr", "ko", "zh-TW") if x in published and x != primary), None)
            mutation_locales = [x for x in (secondary,) if x]
            snap = _shopify_snapshot(cfg, cfg.product_id, locales=mutation_locales)
        except Exception as e:
            # Write a report even if we fail preflight, so you can review what was blocked.
            err = f"Preflight failed: unable to snapshot Shopify product. err={e}"
            ts = _ts_slug()
            report_json_rel = str(getattr(args, "report_json", "") or "").strip() or f"logs/live_dev_test_report_{ts}.json"
            report_md_rel = str(getattr(args, "report_md", "") or "").strip() or f"logs/live_dev_test_report_{ts}.md"
            report_json_abs = os.path.join(_REPO_ROOT, report_json_rel) if not os.path.isabs(report_json_rel) else report_json_rel
            report_md_abs = os.path.join(_REPO_ROOT, report_md_rel) if not os.path.isabs(report_md_rel) else report_md_rel
            for tc in tests:
                outcomes.append(
                    TestOutcome(
                        name=tc.name,
                        expected=tc.expected,
                        actual=None,
                        status="NOT_EXECUTED",
                        error=err,
                    )
                )
            try:
                _write_report_files(outcomes, json_path=report_json_abs, md_path=report_md_abs)
                print(f"[INFO] Report written: {report_json_abs}")
                print(f"[INFO] Report written: {report_md_abs}")
            except Exception as we:
                print(f"[WARN] Failed to write report files after preflight failure: {we}")
            raise TestFailure(f"Failed to snapshot Shopify product. err={e}")

    print(f"== Live Dev Tests == base_url={cfg.api_base_url} shop={cfg.shop_domain} product_id={cfg.product_id}")
    if cfg.full:
        print("Mode: --full (expensive tests enabled)")

    try:
        for tc in tests:
            if tc.expensive and not cfg.full:
                print(f"[SKIP] {tc.name} (use --full)")
                outcomes.append(
                    TestOutcome(
                        name=tc.name,
                        expected=tc.expected,
                        actual=None,
                        status="NOT_EXECUTED",
                        error="Skipped (requires --full)",
                    )
                )
                continue
            if cfg.skip_shopify and tc.requires_shopify_mutation:
                print(f"[SKIP] {tc.name} (--skip-shopify)")
                outcomes.append(
                    TestOutcome(
                        name=tc.name,
                        expected=tc.expected,
                        actual=None,
                        status="NOT_EXECUTED",
                        error="Skipped (--skip-shopify)",
                    )
                )
                continue

            try:
                actual = tc.fn(cfg)
                print(f"[PASS] {tc.name}")
                outcomes.append(
                    TestOutcome(
                        name=tc.name,
                        expected=tc.expected,
                        actual=actual,
                        status="SUCCESS",
                        error=None,
                    )
                )
            except TestFailure as e:
                print(f"[FAIL] {tc.name}: {e}")
                outcomes.append(
                    TestOutcome(
                        name=tc.name,
                        expected=tc.expected,
                        actual=None,
                        status="FAILED",
                        error=str(e),
                    )
                )
            except Exception as e:
                print(f"[ERROR] {tc.name}: {e}")
                print(traceback.format_exc())
                outcomes.append(
                    TestOutcome(
                        name=tc.name,
                        expected=tc.expected,
                        actual=None,
                        status="FAILED",
                        error=f"{e}\n{traceback.format_exc()}",
                    )
                )
    finally:
        # Restore Shopify state if we mutated it
        if not cfg.skip_shopify and not cfg.no_restore and snap is not None:
            try:
                _shopify_restore(cfg, cfg.product_id, snap)
                print("[INFO] Shopify product restored to snapshot state.")
            except Exception as e:
                print(f"[WARN] Failed to restore Shopify product state: {e}")
                print(traceback.format_exc())

    # Write report files
    ts = _ts_slug()
    report_json_rel = str(getattr(args, "report_json", "") or "").strip() or f"logs/live_dev_test_report_{ts}.json"
    report_md_rel = str(getattr(args, "report_md", "") or "").strip() or f"logs/live_dev_test_report_{ts}.md"
    report_json_abs = os.path.join(_REPO_ROOT, report_json_rel) if not os.path.isabs(report_json_rel) else report_json_rel
    report_md_abs = os.path.join(_REPO_ROOT, report_md_rel) if not os.path.isabs(report_md_rel) else report_md_rel
    try:
        _write_report_files(outcomes, json_path=report_json_abs, md_path=report_md_abs)
        print(f"[INFO] Report written: {report_json_abs}")
        print(f"[INFO] Report written: {report_md_abs}")
    except Exception as e:
        print(f"[WARN] Failed to write report files: {e}")

    passed = sum(1 for o in outcomes if o.status == "SUCCESS")
    failed = sum(1 for o in outcomes if o.status == "FAILED")
    skipped = sum(1 for o in outcomes if o.status == "NOT_EXECUTED")
    print(f"== Summary == passed={passed} failed={failed} skipped={skipped}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TestFailure as e:
        print(f"[FATAL] {e}")
        raise SystemExit(2)


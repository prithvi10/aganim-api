import os
import httpx
import asyncio
from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.main.db.db_models import User
from src.main.api.models import RewriteRequest, BulkRewriteRequest
from src.main.service.open_ai_api_service import OpenAIService
from src.main.security.ratelimiter import InMemoryRateLimiter
from src.main.config.configs import (
    LOCAL_RATE_LIMIT_CONFIG,
    SYSTEM_PROMPT,
    LOCALE_PERSONA_MAP,
)
from src.main.utils.text_processor import detect_and_label_sections
from src.main.utils.llm_parser import parse_llm_json, recover_title_desc
from src.main.logging.logger import get_logger
from src.main.db.db_transactions import update_token_usage, get_shop_access_token
from src.main.service.shopify_service import save_product_content_with_locale
from src.main.api.validation import validate_rewrite_request

logger = get_logger(__name__)
limiter = InMemoryRateLimiter(LOCAL_RATE_LIMIT_CONFIG)
openai_service = OpenAIService()

ALLOWED_DISCOVERY_CATEGORIES = {
    "Regional Pedigree",
    "Tactile & Sensory",
    "Time-as-Luxury",
    "Artisan Master",
}


def _normalize_discovered_values(raw: object) -> list[dict]:
    """
    Normalizes model output for discovered_values into a strict, JSON-serializable list.
    Drops any items that don't meet the schema or contain invalid categories.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        explanation = str(item.get("explanation") or "").strip()
        suggested_footer = str(item.get("suggested_footer") or "").strip()
        if category not in ALLOWED_DISCOVERY_CATEGORIES:
            continue
        if not evidence or not explanation or not suggested_footer:
            continue
        out.append(
            {
                "category": category,
                "evidence": evidence,
                "explanation": explanation,
                "suggested_footer": suggested_footer,
            }
        )
    return out


def _to_frontend_discoveries(discovered_values: list[dict]) -> list[dict]:
    """
    Backwards-compatible shape for existing UI cards:
    { category, title, evidence_text, suggested_content }.
    """
    discoveries: list[dict] = []
    for v in discovered_values or []:
        evidence = str(v.get("evidence") or "").strip()
        category = str(v.get("category") or "").strip()
        title = f"{category} — {evidence[:24]}".strip()
        discoveries.append(
            {
                "category": category,
                "title": title,
                "evidence_text": evidence,
                "suggested_content": str(v.get("suggested_footer") or "").strip(),
            }
        )
    return discoveries


def _parse_model_json(raw_content: str) -> tuple[dict, list[dict]]:
    """
    Parses LLM output. Preferred schema (contract-safe):
      { "title": "...", "description": "...", "discovered_values": [...] }
    Back-compat:
      { "rewritten_description": "...", "discovered_values": [...] }
    """
    parsed = parse_llm_json(raw_content)

    # Contract-safe schema: title + description + optional discovered_values
    if isinstance(parsed, dict) and (
        isinstance(parsed.get("title"), str) or isinstance(parsed.get("description"), str)
    ):
        discovered_values = _normalize_discovered_values(parsed.get("discovered_values"))
        data = {
            "title": str(parsed.get("title") or "").strip(),
            "description": str(parsed.get("description") or "").strip(),
        }
        if not data["description"]:
            data["description"] = raw_content
        return data, discovered_values

    # Back-compat schema: rewritten_description + optional discovered_values
    if isinstance(parsed, dict) and isinstance(parsed.get("rewritten_description"), str):
        discovered_values = _normalize_discovered_values(parsed.get("discovered_values"))
        data = {
            "title": "",
            "description": parsed.get("rewritten_description") or "",
        }
        if not data["description"]:
            data["description"] = raw_content
        return data, discovered_values

    legacy = parsed if isinstance(parsed, dict) else None
    legacy = legacy or recover_title_desc(raw_content)
    if isinstance(legacy, dict):
        return (
            {
                "title": str(legacy.get("title") or ""),
                "description": str(legacy.get("description") or raw_content),
            },
            [],
        )

    return ({"title": "", "description": raw_content}, [])


def _build_dynamic_prompt(target_locale: str) -> str:
    market_persona = LOCALE_PERSONA_MAP.get(target_locale, "Global English Market")
    return f"""{SYSTEM_PROMPT}

TARGET LANGUAGE: {target_locale}
MARKET PERSONA: {market_persona}

ADDITIONAL LOCALIZATION RULES:
- Write both "title" and "description" in the TARGET LANGUAGE ({target_locale}) only.
- Use local idioms and market-specific triggers for {market_persona}. Avoid literal English/Japanese if not the target.
- For zh-TW: prefer Taiwanese Mandarin expressions and highlight CP値/CP ratio.
- For ko: keep tone natural for Korean shoppers.
- Keep JSON shape exactly: {{"title": "...", "description": "...", "discovered_values": [...]}}.
- Only extract values for which there is clear evidence in the text. Do not hallucinate or add history for crafts not mentioned.

SECTION TAGS:
- The Japanese input may include [Section: LABEL] ... [/Section] markers. Preserve order. For each Section, create a distinct <h3> with that LABEL. Do not merge sections. Use <hr /> between major section groups if needed.
"""

async def _generate_and_save_for_locale(
    db: Session,
    shop: str,
    product_id: int | None,
    product_name: str,
    category: str,
    processed_description: str,
    target_locale: str,
    primary_locale: str,
    access_token: str | None,
    user_id: int,
    billing_cycle_start,
):
    """
    Helper to generate copy for a single locale and save it to Shopify.
    """
    dynamic_prompt = _build_dynamic_prompt(target_locale)
    
    openai_response = openai_service.generate_copy(
        product_name=product_name,
        category=category,
        japanese_description=processed_description,
        system_prompt=dynamic_prompt
    )
    
    total_tokens = getattr(openai_response.usage, 'total_tokens', 0) if openai_response.usage else 0
    if total_tokens > 0:
        update_token_usage(db, user_id, total_tokens, billing_cycle_start)

    raw_content = openai_response.choices[0].message.content
    parsed, discovered_values = _parse_model_json(raw_content or "")
    # Preserve existing contract: always return a title string to clients.
    if not str(parsed.get("title") or "").strip():
        parsed["title"] = product_name or "Generated Copy"
    if not str(parsed.get("description") or "").strip():
        parsed["description"] = raw_content or ""

    if product_id and access_token:
        title_to_save = parsed.get("title") or product_name or "Translated Product"
        desc_to_save = parsed.get("description") or raw_content or ""
        logger.info(f"[Save] shop={shop} pid={product_id} target={target_locale} primary={primary_locale} title_sample={title_to_save[:80]}")
        await save_product_content_with_locale(
            shop_domain=shop,
            access_token=access_token,
            product_id=product_id,
            title=title_to_save,
            description=desc_to_save,
            target_locale=target_locale,
            shop_primary_locale=primary_locale,
        )
    
    return {
        "locale": target_locale,
        "data": parsed,
        "tokens": total_tokens,
        "discovered_values": discovered_values,
    }

async def process_generation_request(
    db: Session,
    request: RewriteRequest,
    user: User,
    plan,
    user_id: int,
    billing_cycle_start
):
    shop = user.username
    if not limiter.is_allowed(shop):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")
    
    if request.stream and not plan.can_stream_responses:
        raise HTTPException(status_code=403, detail="Streaming not supported on your current plan.")

    target_locale = request.target_locale or "en"
    dynamic_prompt = _build_dynamic_prompt(target_locale)

    try:
        if request.stream:
            logger.info(f"🌊 Initiating Streaming Response for: {shop}")
            return openai_service.create_streaming_response(
                product_name=request.product_name,
                category=request.category,
                japanese_description=request.japanese_description,
                db=db,
                user_id=user_id,
                billing_cycle_start=billing_cycle_start,
                system_prompt=dynamic_prompt
            )

        # Standard non-streaming flow
        processed_desc = detect_and_label_sections(request.japanese_description)
        access_token = get_shop_access_token(db, shop) if request.product_id else None
        
        if request.product_id and not access_token:
            logger.error(f"❌ Access Token missing for shop {shop} during product update.")
            raise HTTPException(status_code=500, detail="Shopify Access Token not found. Re-install app.")

        # Need primary locale for routing REST/GraphQL
        primary_locale = "en"
        if access_token:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://{shop}/admin/api/2024-07/shop.json", 
                        headers={"X-Shopify-Access-Token": access_token}
                    )
                    if resp.status_code == 200:
                        primary_locale = resp.json().get("shop", {}).get("primary_locale", "en")
            except Exception: pass

        result = await _generate_and_save_for_locale(
            db, shop, request.product_id, request.product_name, request.category,
            processed_desc, target_locale, primary_locale, access_token, user_id, billing_cycle_start,
        )
        
        resp = {"status": "success", "data": result["data"]}
        discovered_values = result.get("discovered_values") or []
        if discovered_values:
            resp["discovered_values"] = discovered_values
            resp["discoveries"] = _to_frontend_discoveries(discovered_values)
        return resp

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing request for {shop}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_bulk_generation_request(
    db: Session,
    request: BulkRewriteRequest,
    user: User,
    plan,
    user_id: int,
    billing_cycle_start
):
    """
    Core logic for bulk generation requests.
    Checks plan, rate limits, and parallelizes generation for multiple locales.
    """
    shop = user.username
    if not limiter.is_allowed(shop):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")

    # 1. Plan Check for Bulk (Multi-locale)
    if len(request.target_locales) > 1 and plan.name not in ("Pro", "Growth"):
        raise HTTPException(status_code=403, detail="Bulk multi-market generation requires Pro plan.")

    try:
        access_token = get_shop_access_token(db, shop) if request.product_id else None
        if request.product_id and not access_token:
            raise HTTPException(status_code=500, detail="Shopify Access Token not found.")

        # 2. Fetch Primary Locale once
        primary_locale = "en"
        if access_token:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"https://{shop}/admin/api/2024-07/shop.json", 
                        headers={"X-Shopify-Access-Token": access_token}
                    )
                    if resp.status_code == 200:
                        primary_locale = resp.json().get("shop", {}).get("primary_locale", "en")
            except Exception: pass

        processed_desc = detect_and_label_sections(request.japanese_description)

        # 3. Save ordering to avoid translation digest invalidation:
        # If the primary locale is included, update it LAST. Otherwise translationsRegister for
        # secondary locales can fail with "Translatable content hash is invalid" if primary content
        # changes during the digest->register window.
        target_locales = list(request.target_locales or [])
        non_primary_locales = [l for l in target_locales if l != primary_locale]
        primary_locales = [l for l in target_locales if l == primary_locale]

        def _task(locale: str):
            return _generate_and_save_for_locale(
                db,
                shop,
                request.product_id,
                request.product_name,
                request.category,
                processed_desc,
                locale,
                primary_locale,
                access_token,
                user_id,
                billing_cycle_start,
            )

        results: list = []

        # Phase 1: run non-primary locales in parallel
        if non_primary_locales:
            results.extend(
                await asyncio.gather(*[_task(l) for l in non_primary_locales], return_exceptions=True)
            )

        # Phase 2: run primary locale LAST (typically one locale)
        if primary_locales:
            results.extend(
                await asyncio.gather(*[_task(l) for l in primary_locales], return_exceptions=True)
            )
        
        success_locales = []
        failed_locales = []
        results_data = {}
        
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Bulk item failed: {res}")
                failed_locales.append(str(res))
            else:
                locale = res["locale"]
                success_locales.append(locale)
                results_data[locale] = res["data"]

        resp = {
            "status": "success",
            "processed": success_locales,
            "failed": failed_locales,
            "results": results_data
        }
        # Use discovered_values from the first successful locale (they should be stable across locales).
        first_values: list[dict] = []
        for res in results:
            if isinstance(res, Exception):
                continue
            vals = res.get("discovered_values") or []
            if vals:
                first_values = vals
                break
        if first_values:
            resp["discovered_values"] = first_values
            resp["discoveries"] = _to_frontend_discoveries(first_values)
        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in bulk processing for {shop}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

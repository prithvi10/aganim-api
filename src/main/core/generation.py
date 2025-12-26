import os
import httpx
import asyncio
from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.main.db.db_models import User
from src.main.api.models import RewriteRequest, BulkRewriteRequest
from src.main.service.open_ai_api_service import OpenAIService
from src.main.security.ratelimiter import InMemoryRateLimiter
from src.main.config.configs import LOCAL_RATE_LIMIT_CONFIG, SYSTEM_PROMPT
from src.main.utils.text_processor import detect_and_label_sections
from src.main.utils.llm_parser import parse_llm_json, recover_title_desc
from src.main.logging.logger import get_logger
from src.main.db.db_transactions import update_token_usage, get_shop_access_token
from src.main.service.shopify_service import save_product_content_with_locale
from src.main.api.validation import validate_rewrite_request

logger = get_logger(__name__)
limiter = InMemoryRateLimiter(LOCAL_RATE_LIMIT_CONFIG)
openai_service = OpenAIService()

LOCALE_PERSONA_MAP = {
    "en": "US Amazon Market",
    "zh-TW": "Taiwan Shopee Market (use Taiwanese Mandarin and emphasize CP値/CP ratio)",
    "ko": "Korean Coupang Market (use natural Korean marketing tone)"
}

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
- Keep JSON shape exactly: {{"title": "...", "description": "..."}}.

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
    billing_cycle_start
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
    parsed = parse_llm_json(raw_content) or recover_title_desc(raw_content)
    
    if not parsed:
        parsed = {"title": "Generated Copy", "description": raw_content}

    if product_id and access_token:
        await save_product_content_with_locale(
            shop_domain=shop,
            access_token=access_token,
            product_id=product_id,
            title=parsed.get("title", "Translated Product"),
            description=parsed.get("description", raw_content),
            target_locale=target_locale,
            shop_primary_locale=primary_locale,
        )
    
    return {"locale": target_locale, "data": parsed, "tokens": total_tokens}

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
            processed_desc, target_locale, primary_locale, access_token, user_id, billing_cycle_start
        )
        
        return {"status": "success", "data": result["data"]}

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
    if len(request.target_locales) > 1 and plan.name != "Global Pro":
        raise HTTPException(status_code=403, detail="Bulk multi-market generation requires Global Pro plan.")

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

        # 3. Parallelize generations
        tasks = [
            _generate_and_save_for_locale(
                db, shop, request.product_id, request.product_name, request.category,
                processed_desc, locale, primary_locale, access_token, user_id, billing_cycle_start
            )
            for locale in request.target_locales
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_locales = []
        failed_locales = []
        
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Bulk item failed: {res}")
                failed_locales.append(str(res))
            else:
                success_locales.append(res["locale"])

        return {
            "status": "success",
            "processed": success_locales,
            "failed": failed_locales
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in bulk processing for {shop}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

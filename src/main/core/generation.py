import os
import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session
from src.main.db.db_models import User
from src.main.api.models import RewriteRequest
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

async def process_generation_request(
    db: Session,
    request: RewriteRequest,
    user: User,
    plan,
    user_id: int,
    billing_cycle_start
):
    """
    Core business logic for processing generation requests.
    Orchestrates rate limiting, validation, LLM call, and Shopify persistence.
    """
    shop = user.username

    # 1. Check Rate Limit
    if not limiter.is_allowed(shop):
        logger.warning(f"Rate limit exceeded for shop: {shop}")
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")
    
    # 2. Check Streaming Capability
    if request.stream and not plan.can_stream_responses:
        raise HTTPException(status_code=403, detail="Streaming not supported on your current plan.")

    # 3. Build dynamic prompt with locale + market persona
    locale_persona_map = {
        "en": "US Amazon Market",
        "zh-TW": "Taiwan Shopee Market (use Taiwanese Mandarin and emphasize CP値/CP ratio)",
        "ko": "Korean Coupang Market (use natural Korean marketing tone)"
    }

    target_locale = request.target_locale or "en"
    market_persona = locale_persona_map.get(target_locale, "Global English Market")

    dynamic_prompt = f"""{SYSTEM_PROMPT}

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

    try:
        # 4. Handle Streaming
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

        # 5. Handle Standard Request
        processed_description = detect_and_label_sections(request.japanese_description)

        openai_response = openai_service.generate_copy(
            product_name=request.product_name,
            category=request.category,
            japanese_description=processed_description,
            system_prompt=dynamic_prompt
        )
        
        # 6. Usage Metering
        total_tokens_used = 0
        if hasattr(openai_response, 'usage') and openai_response.usage:
            total_tokens_used = openai_response.usage.total_tokens
        
        if total_tokens_used > 0:
            update_token_usage(db, user_id, total_tokens_used, billing_cycle_start)

        # Parse JSON response
        raw_content = openai_response.choices[0].message.content
        parsed_content = parse_llm_json(raw_content)
        if not parsed_content:
            recovered = recover_title_desc(raw_content)
            if recovered:
                logger.warning(f"⚠️ LLM JSON parse failed; recovered fields for {shop}.")
                parsed_content = recovered
            else:
                logger.warning(f"⚠️ LLM did not return valid JSON for {shop}. Returning raw text as description.")
                parsed_content = {
                    "title": "Generated Copy",
                    "description": raw_content
                }

        # 7. Save Changes to Shopify
        if request.product_id:
            access_token = get_shop_access_token(db, shop)
            if not access_token:
                logger.error(f"❌ Access Token missing for shop {shop} during product update.")
                raise HTTPException(status_code=500, detail="Shopify Access Token not found. Re-install app.")

            final_title = parsed_content.get("title", "Translated Product")
            final_desc = parsed_content.get("description", raw_content)

            shopify_api_version = os.getenv("SHOPIFY_API_VERSION", "2024-07")
            headers = {
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json"
            }

            primary_locale = "en"
            try:
                shop_info_url = f"https://{shop}/admin/api/{shopify_api_version}/shop.json"
                async with httpx.AsyncClient() as client:
                    shop_resp = await client.get(shop_info_url, headers=headers)
                    if shop_resp.status_code == 200:
                        primary_locale = shop_resp.json().get("shop", {}).get("primary_locale", "en")
            except Exception as e:
                logger.warning(f"⚠️ Failed to fetch primary locale, assuming 'en': {e}")

            target_locale = request.target_locale or primary_locale

            await save_product_content_with_locale(
                shop_domain=shop,
                access_token=access_token,
                product_id=request.product_id,
                title=final_title,
                description=final_desc,
                target_locale=target_locale,
                shop_primary_locale=primary_locale,
            )

        logger.info(f"✅ Translated for {shop}. Tokens: {total_tokens_used}")
        return {
            "status": "success",
            "data": parsed_content
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing request for {shop}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


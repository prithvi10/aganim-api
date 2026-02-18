from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import os
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.shared.logging.logger import get_logger
from src.ecommerce.services.openai_legacy_service import OpenAIService
from src.ecommerce.services import ServiceRegistry, LLMService, SerpService
from src.shared.utils.llm_parser import parse_llm_json
from src.ecommerce.services.value_discovery_service import ValueDiscoveryService
from src.ecommerce.agents.marketing.holidays import (
    Holiday as _CanonicalHoliday,
    get_next_upcoming_holiday as _canonical_next_holiday,
    generate_discount_code as _canonical_discount_code,
)

logger = get_logger(__name__)
openai_service = OpenAIService()
value_discovery_service = ValueDiscoveryService()


def _run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop and loop.is_running():
        # We're in an async context, create a new task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


def _clean_hashtag(tag: str) -> str | None:
    t = (tag or "").strip()
    if not t:
        return None
    if t.startswith("#"):
        t = t[1:]
    t = re.sub(r"[^0-9A-Za-z_]", "", t)
    if not t:
        return None
    return f"#{t}"


def _suggest_hashtags(product_title: str, category: str, tags: list[str] | None = None) -> list[str]:
    base = [
        _clean_hashtag(category.replace(" ", "")),
        _clean_hashtag("Shopify"),
        _clean_hashtag("SmallBusiness"),
        _clean_hashtag("NewArrivals"),
    ]
    title_bits = re.split(r"\s+", (product_title or "").strip())
    base.extend([_clean_hashtag(b) for b in title_bits[:3]])
    if tags:
        base.extend([_clean_hashtag(t) for t in tags[:6]])

    deduped: list[str] = []
    for t in base:
        if t and t not in deduped:
            deduped.append(t)
    return deduped[:12]


def _format_caption(caption: str, hashtags: list[str]) -> str:
    caption = (caption or "").strip()
    tagline = " ".join([t for t in hashtags if t])
    if tagline:
        return f"{caption}\n\n{tagline}".strip()
    return caption


# ------------------------------------------------------------------------------
# Seasonal holiday helpers (US)
# ------------------------------------------------------------------------------
Holiday = _CanonicalHoliday


def _next_upcoming_holiday(today: date) -> Holiday | None:
    return _canonical_next_holiday(today)


def _discount_code_name(holiday_name: str, category: str, year: int) -> str:
    return _canonical_discount_code(holiday_name, category, year)


# ------------------------------------------------------------------------------
# Agent actions
# ------------------------------------------------------------------------------
def social_hook_architect_action(product_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    rid = str((context or {}).get("request_id") or "-")
    product_title = str(product_data.get("title") or product_data.get("product_name") or "").strip()
    category = str(product_data.get("category") or product_data.get("productType") or "General").strip()
    tags = product_data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    focus = str(context.get("focus") or "Instagram Reels").strip()

    hashtags = _suggest_hashtags(product_title, category, tags if isinstance(tags, list) else None)

    # Prefer OpenAI, but provide deterministic fallback if missing key.
    use_ai = bool(os.getenv("OPENAI_API_KEY"))
    hooks: list[dict[str, Any]] = []
    overlay_suggestions: list[str] = [
        "3 benefits in 3 seconds",
        "Before → After",
        "POV: You finally found the one",
    ]

    if use_ai and product_title:
        logger.info("[AgentAction] rid=%s action=social_hook_architect mode=ai", rid)
        system = (
            "You are a senior social media strategist. "
            "Return ONLY valid JSON. No markdown fences."
        )
        user = {
            "platform": "instagram",
            "format": focus,
            "product": {
                "title": product_title,
                "category": category,
                "tags": tags,
            },
            "task": (
                "Generate 3 viral hooks: Aesthetic, Educational, Viral. "
                "Each must include a short caption (<=220 chars) and 8-12 hashtags. "
                "Also provide 3 short text-overlay suggestions for Reels (<=28 chars each)."
            ),
            "output_schema": {
                "hooks": [
                    {"type": "Aesthetic|Educational|Viral", "caption": "string", "hashtags": ["#tag"], "overlay": "string"}
                ],
                "overlay_suggestions": ["string"],
            },
        }

        raw = openai_service.generate_json(system_prompt=system, user_json=user, temperature=0.8, max_tokens=450)
        parsed = parse_llm_json(raw) or {}
        hooks = parsed.get("hooks") if isinstance(parsed.get("hooks"), list) else []
        overlay_suggestions = (
            parsed.get("overlay_suggestions")
            if isinstance(parsed.get("overlay_suggestions"), list)
            else overlay_suggestions
        )

    if not hooks:
        logger.info("[AgentAction] rid=%s action=social_hook_architect mode=fallback", rid)
        # Fallback: template-based hooks
        hooks = [
            {
                "type": "Aesthetic",
                "caption": f"Unboxing {product_title or 'this'} is the kind of *small luxury* you feel instantly. ✨",
                "hashtags": hashtags,
                "overlay": "Small luxury, big vibe",
            },
            {
                "type": "Educational",
                "caption": f"Quick tip: how to get the most out of {product_title or 'this'} in 10 seconds.",
                "hashtags": hashtags,
                "overlay": "Quick tip (10s)",
            },
            {
                "type": "Viral",
                "caption": f"POV: you tried {product_title or 'this'} once and now you recommend it to everyone 😅",
                "hashtags": hashtags,
                "overlay": "POV: obsessed",
            },
        ]

    # Normalize + build copyable strings
    normalized: list[dict[str, Any]] = []
    for h in hooks[:3]:
        h_type = str(h.get("type") or "").strip() or "Hook"
        caption = str(h.get("caption") or "").strip()
        h_tags = h.get("hashtags")
        if not isinstance(h_tags, list):
            h_tags = hashtags
        h_tags = [t for t in ([_clean_hashtag(x) for x in h_tags] if isinstance(h_tags, list) else hashtags) if t]
        overlay = str(h.get("overlay") or "").strip()
        normalized.append(
            {
                "type": h_type,
                "caption": caption,
                "hashtags": h_tags,
                "overlay": overlay,
                "copy_text": _format_caption(caption, h_tags),
            }
        )

    return {
        "text": normalized[0]["copy_text"] if normalized else "",
        "metadata": {
            "focus": focus,
            "hooks": normalized,
            "overlay_suggestions": [str(s).strip() for s in overlay_suggestions if str(s).strip()][:5],
            "instagram_create_url": "https://www.instagram.com/reels/create/",
        },
    }


def seasonal_campaign_agent_action(product_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    category = str(product_data.get("category") or product_data.get("productType") or "General").strip()
    today_raw = context.get("current_date") or context.get("date") or context.get("today")

    try:
        if isinstance(today_raw, str) and today_raw:
            today = datetime.fromisoformat(today_raw.replace("Z", "+00:00")).date()
        else:
            today = date.today()
    except Exception:
        today = date.today()

    holiday = _next_upcoming_holiday(today)
    if not holiday:
        return {
            "text": "",
            "metadata": {"should_show": False},
        }

    days_until = (holiday.date - today).days
    should_show = days_until <= 42

    title = f"{holiday.name} {category} Campaign"
    discount_code = _discount_code_name(holiday.name, category, holiday.date.year)

    return {
        "text": title,
        "metadata": {
            "should_show": should_show,
            "holiday": {
                "name": holiday.name,
                "date": holiday.date.isoformat(),
                "days_until": days_until,
            },
            "campaign": {
                "title": title,
                "discount_code_name": discount_code,
                "marketing_channel_type": "SOCIAL",
                "utm": {"source": "app", "medium": "social"},
            },
        },
    }


def seasonal_campaign_caption_action(product_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Generates a seasonal, holiday-tied caption for the selected product.
    Intended for the /app/marketing UI to request an additional caption that matches
    the upcoming seasonal campaign vibe.
    """
    rid = str((context or {}).get("request_id") or "-")
    product_title = str(product_data.get("title") or product_data.get("product_name") or "").strip()
    category = str(product_data.get("category") or product_data.get("productType") or "General").strip()
    tags = product_data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    today_raw = context.get("current_date") or context.get("date") or context.get("today")
    try:
        if isinstance(today_raw, str) and today_raw:
            today = datetime.fromisoformat(today_raw.replace("Z", "+00:00")).date()
        else:
            today = date.today()
    except Exception:
        today = date.today()

    holiday = _next_upcoming_holiday(today)
    if not holiday:
        logger.info("[AgentAction] rid=%s action=seasonal_campaign_caption no_holiday", rid)
        return {"text": "", "metadata": {"should_show": False}}

    days_until = (holiday.date - today).days
    should_show = days_until <= 42

    hashtags = _suggest_hashtags(product_title, category, tags if isinstance(tags, list) else None)
    discount_code = _discount_code_name(holiday.name, category, holiday.date.year)
    campaign_title = f"{holiday.name} {category} Campaign"

    use_ai = bool(os.getenv("OPENAI_API_KEY"))
    caption = ""

    if use_ai and product_title:
        logger.info("[AgentAction] rid=%s action=seasonal_campaign_caption mode=ai holiday=%s", rid, holiday.name)
        system = (
            "You are a senior social media strategist. "
            "Return ONLY valid JSON. No markdown fences."
        )
        user = {
            "platform": "instagram",
            "holiday": {"name": holiday.name, "date": holiday.date.isoformat(), "days_until": days_until},
            "product": {"title": product_title, "category": category, "tags": tags},
            "constraints": {
                "caption_max_chars": 220,
                "tone": "warm, seasonal, authentic",
                "no_invented_claims": True,
            },
            "output_schema": {"caption": "string", "cta": "string"},
        }
        raw = openai_service.generate_json(
            system_prompt=system,
            user_json=user,
            temperature=0.8,
            max_tokens=220,
        )
        parsed = parse_llm_json(raw) or {}
        caption = str(parsed.get("caption") or "").strip()

    if not caption:
        logger.info("[AgentAction] rid=%s action=seasonal_campaign_caption mode=fallback holiday=%s", rid, holiday.name)
        # Deterministic fallback
        caption = (
            f"{holiday.name} is coming 💡 Treat yourself (or someone you love) to {product_title or 'a favorite'}.\n"
            f"Use code {discount_code} (limited time)."
        ).strip()

    return {
        "text": _format_caption(caption, hashtags),
        "metadata": {
            "should_show": should_show,
            "holiday": {"name": holiday.name, "date": holiday.date.isoformat(), "days_until": days_until},
            "campaign": {"title": campaign_title, "discount_code_name": discount_code},
            "caption": caption,
            "hashtags": hashtags,
            "copy_text": _format_caption(caption, hashtags),
        },
    }


def value_discovery_action(product_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic evidence-discovery for Japanese craftsmanship value.
    Returns a list of discovery objects; returns an empty list if no matches.
    """
    title = str(product_data.get("title") or product_data.get("product_name") or "").strip()
    description = str(product_data.get("description") or product_data.get("japanese_description") or "").strip()
    discoveries = value_discovery_service.discover(title=title, description=description)
    return {
        "text": "",
        "metadata": {
            "discoveries": discoveries,
        },
    }


# ------------------------------------------------------------------------------
# SEO Optimize Action (synchronous wrapper for SEOAgent)
# ------------------------------------------------------------------------------
def seo_optimize_action(
    product_data: dict[str, Any],
    context: dict[str, Any],
    db: Any = None,
    shop_domain: str | None = None,
) -> dict[str, Any]:
    """
    Synchronous SEO optimization action.
    
    Generates SEO metadata (title, description, alt-text) and runs CTR check.
    Does NOT store in database - returns results directly.
    Usage is tracked if db/shop_domain are provided.
    """
    rid = str((context or {}).get("request_id") or "-")
    product_title = str(product_data.get("title") or product_data.get("product_name") or "").strip()
    description = str(product_data.get("description") or product_data.get("japanese_description") or "").strip()
    category = str(product_data.get("category") or product_data.get("productType") or "General").strip()
    target_locale = str(context.get("target_locale") or "en").strip()
    
    logger.info("[AgentAction] rid=%s action=seo_optimize product=%s", rid, product_title[:50])
    
    async def _run_seo():
        # Create services with db/shop for usage tracking
        services = ServiceRegistry.create_default(db=db, shop_domain=shop_domain)
        
        # Step 1: Fetch SERP results for competitor insights
        serp_results = []
        search_query = f"{product_title} {category}".strip()
        if search_query:
            try:
                results = await services.serp.search(query=search_query, num_results=3)
                serp_results = [
                    {
                        "title": r.title,
                        "snippet": r.snippet,
                        "link": r.link,
                        "position": r.position,
                    }
                    for r in results
                ]
            except Exception as e:
                logger.warning("[AgentAction] rid=%s SERP fetch failed: %s", rid, e)
        
        # Step 2: Generate SEO metadata using LLM
        from src.ecommerce.agents.seo.prompts import SEO_SYSTEM_PROMPT, SEO_USER_PROMPT_TEMPLATE
        
        serp_context = ""
        if serp_results:
            serp_lines = []
            for r in serp_results[:3]:
                serp_lines.append(
                    f"#{r.get('position', '?')}: {r.get('title', 'N/A')}\n"
                    f"   Snippet: {r.get('snippet', 'N/A')[:200]}"
                )
            serp_context = "\n\n".join(serp_lines)
        else:
            serp_context = "No competitor data available."
        
        user_prompt = SEO_USER_PROMPT_TEMPLATE.format(
            title=product_title,
            category=category,
            target_locale=target_locale,
            description=description[:2000],
            serp_context=serp_context,
        )
        
        seo_result = {}
        try:
            result = await services.llm.generate_text(
                prompt=user_prompt,
                system_prompt=SEO_SYSTEM_PROMPT,
                model="gpt-4o-mini",
                temperature=0.3,
            )
            seo_result = parse_llm_json(result) or {}
        except Exception as e:
            logger.error("[AgentAction] rid=%s SEO LLM failed: %s", rid, e)
        
        # Step 3: Run CTR/PST check (deterministic)
        from src.ecommerce.agents.seo.prompts import PST_PAIN_PATTERNS, PST_SOLUTION_PATTERNS, PST_TRUST_PATTERNS
        
        text = f"{description} {seo_result.get('seo_description', '')}".lower()
        pain_present = any(re.search(p, text, re.IGNORECASE) for p in PST_PAIN_PATTERNS)
        solution_present = any(re.search(p, text, re.IGNORECASE) for p in PST_SOLUTION_PATTERNS)
        trust_present = any(re.search(p, text, re.IGNORECASE) for p in PST_TRUST_PATTERNS)
        
        score = 0.0
        if pain_present:
            score += 0.33
        if solution_present:
            score += 0.34
        if trust_present:
            score += 0.33
        
        suggestions = []
        if not pain_present:
            suggestions.append("Add a question or pain point to hook readers")
        if not solution_present:
            suggestions.append("Include a concrete benefit with a specific feature/spec")
        if not trust_present:
            suggestions.append("Add a trust cue (origin, craftsmanship, guarantee, shipping)")
        
        ctr_check = {
            "pain_present": pain_present,
            "solution_present": solution_present,
            "trust_present": trust_present,
            "score": round(score, 2),
            "suggestions": suggestions,
        }
        
        return {
            "seo_title": seo_result.get("seo_title", ""),
            "seo_description": seo_result.get("seo_description", ""),
            "seo_alt_text": seo_result.get("seo_alt_text", ""),
            "seo_insights": seo_result.get("seo_insights", {}),
            "ctr_check": ctr_check,
            "serp_insights": serp_results,
        }
    
    result = _run_async(_run_seo())
    
    logger.info("[AgentAction] rid=%s action=seo_optimize done", rid)
    
    return {
        "text": result.get("seo_title", ""),
        "metadata": result,
    }


# ------------------------------------------------------------------------------
# Price Scout Action (synchronous wrapper with Smart Price Discovery)
# ------------------------------------------------------------------------------
def price_scout_action(
    product_data: dict[str, Any],
    context: dict[str, Any],
    db: Any = None,
    shop_domain: str | None = None,
) -> dict[str, Any]:
    """
    Synchronous Smart Price Discovery action.
    
    Flow (2 LLM calls):
    1. Fetch 20 competitors from Google Shopping API
    2. Semantic filter to keep only true comparables (LLM call 1)
    3. Calculate min/max/avg/median from filtered list
    4. Generate pricing recommendation (LLM call 2)
    
    Does NOT store in database - returns results directly.
    Usage is tracked if db/shop_domain are provided.
    """
    import json
    import statistics
    
    rid = str((context or {}).get("request_id") or "-")
    product_title = str(product_data.get("title") or product_data.get("product_name") or "").strip()
    description = str(product_data.get("description") or product_data.get("japanese_description") or "").strip()
    category = str(product_data.get("category") or product_data.get("productType") or "General").strip()
    
    logger.info("[AgentAction] rid=%s action=price_scout product=%s", rid, product_title[:50])
    
    async def _run_price_scout():
        # Create services with db/shop for usage tracking
        services = ServiceRegistry.create_default(db=db, shop_domain=shop_domain)
        
        # === STEP 1: Fetch competitors from Google Shopping API ===
        raw_competitors = []
        try:
            raw_competitors = await services.serp.get_competitor_prices(
                product_name=product_title,
                category=category,
                num_results=20,  # Request 20 for good sample pool
            )
            logger.info("[AgentAction] rid=%s Fetched %d shopping results", rid, len(raw_competitors))
        except Exception as e:
            logger.warning("[AgentAction] rid=%s Shopping fetch failed: %s", rid, e)
        
        # If no competitors, return empty analysis
        if not raw_competitors:
            from src.ecommerce.agents.price_scout.prompts import NO_COMPETITORS_MESSAGE
            return {
                "competitor_avg_price": 0.0,
                "recommended_price": 0.0,
                "price_position": "unknown",
                "confidence": 0.0,
                "reasoning": NO_COMPETITORS_MESSAGE,
                "competitor_count": 0,
                "valid_competitors": [],
                "market_analysis": None,
                "filter_reasoning": "No competitors fetched from Google Shopping.",
                "raw_competitor_count": 0,
            }
        
        # === STEP 2: Semantic Filtering (LLM Call 1) ===
        from src.ecommerce.agents.price_scout.prompts import (
            FILTER_COMPETITORS_PROMPT,
            SYSTEM_PROMPT,
            ANALYSIS_WITH_METRICS_PROMPT,
        )
        from src.ecommerce.agents.price_scout.schemas import (
            FilteredCompetitorsResponse,
            PricingAnalysis,
        )
        
        # Format competitors for filtering prompt
        competitors_for_prompt = [
            {
                "index": i,
                "title": c.get("title", ""),
                "price": c.get("price", ""),
                "extracted_price": c.get("extracted_price"),
                "source": c.get("source", ""),
                "link": c.get("link", ""),
            }
            for i, c in enumerate(raw_competitors)
        ]
        
        filter_prompt = FILTER_COMPETITORS_PROMPT.format(
            product_title=product_title,
            product_description=description or product_title,
            category=category,
            competitors_json=json.dumps(competitors_for_prompt, indent=2),
        )
        
        valid_competitors = raw_competitors
        filter_reasoning = "Filtering skipped."
        
        try:
            filter_response = await services.llm.generate_structured(
                prompt=filter_prompt,
                response_format=FilteredCompetitorsResponse,
                system_prompt="You are a Market Analyst specializing in e-commerce product comparison.",
                model="gpt-4o-mini",
                temperature=0.0,
            )
            
            valid_indices = set(filter_response.valid_competitor_indices)
            valid_competitors = [
                c for i, c in enumerate(raw_competitors)
                if i in valid_indices
            ]
            filter_reasoning = filter_response.reasoning
            
            logger.info(
                "[AgentAction] rid=%s Semantic filter: %d/%d kept",
                rid,
                len(valid_competitors),
                len(raw_competitors),
            )
            
        except Exception as e:
            logger.warning("[AgentAction] rid=%s Semantic filtering failed: %s", rid, e)
            # Fallback: use top 5 raw results
            valid_competitors = raw_competitors[:5]
            filter_reasoning = f"Filtering failed, using top results: {str(e)}"
        
        # If all filtered out, use top raw results
        if not valid_competitors:
            valid_competitors = raw_competitors[:5]
            filter_reasoning += " (Fallback: using top raw results)"
        
        # === STEP 3: Calculate Market Metrics (No LLM) ===
        prices = [
            c["extracted_price"]
            for c in valid_competitors
            if c.get("extracted_price") and c["extracted_price"] > 0
        ]
        
        if prices:
            market_analysis = {
                "min_price": min(prices),
                "max_price": max(prices),
                "average_price": sum(prices) / len(prices),
                "median_price": statistics.median(prices),
                "competitor_count": len(prices),
            }
        else:
            market_analysis = {
                "min_price": 0.0,
                "max_price": 0.0,
                "average_price": 0.0,
                "median_price": 0.0,
                "competitor_count": 0,
            }
        
        # === STEP 4: Generate Pricing Recommendation (LLM Call 2) ===
        competitor_text = "\n".join([
            f"- {c.get('title', 'Unknown')} ({c.get('source', 'Unknown')}): {c.get('price', 'N/A')}"
            for c in valid_competitors[:10]
        ])
        
        analysis_prompt = ANALYSIS_WITH_METRICS_PROMPT.format(
            product_name=product_title,
            product_description=description or product_title,
            category=category,
            competitor_count=market_analysis.get("competitor_count", 0),
            min_price=market_analysis.get("min_price", 0),
            max_price=market_analysis.get("max_price", 0),
            average_price=market_analysis.get("average_price", 0),
            median_price=market_analysis.get("median_price", 0),
            competitor_text=competitor_text,
            filter_reasoning=filter_reasoning,
        )
        
        try:
            analysis = await services.llm.generate_structured(
                prompt=analysis_prompt,
                response_format=PricingAnalysis,
                system_prompt=SYSTEM_PROMPT,
                model="gpt-4o-mini",
                temperature=0.0,
            )
            
            analysis_dict = analysis.model_dump()
            analysis_dict["competitor_avg_price"] = market_analysis.get("average_price", 0)
            analysis_dict["competitor_count"] = market_analysis.get("competitor_count", 0)
            
        except Exception as e:
            logger.error("[AgentAction] rid=%s Price analysis LLM failed: %s", rid, e)
            analysis_dict = {
                "competitor_avg_price": market_analysis.get("average_price", 0),
                "recommended_price": market_analysis.get("median_price", 0),
                "price_position": "competitive",
                "confidence": 0.3,
                "reasoning": f"Analysis failed, using median as fallback: {str(e)}",
                "competitor_count": market_analysis.get("competitor_count", 0),
            }
        
        # Return enriched result
        return {
            **analysis_dict,
            "valid_competitors": valid_competitors,
            "market_analysis": market_analysis,
            "filter_reasoning": filter_reasoning,
            "raw_competitor_count": len(raw_competitors),
        }
    
    result = _run_async(_run_price_scout())
    
    logger.info(
        "[AgentAction] rid=%s action=price_scout done filtered=%d/%d",
        rid,
        len(result.get("valid_competitors", [])),
        result.get("raw_competitor_count", 0),
    )
    
    return {
        "text": f"Recommended price: ${result.get('recommended_price', 0):.2f}" if result.get('recommended_price') else "",
        "metadata": {
            "pricing_analysis": result,
        },
    }


def run_agent_action(
    action: str,
    product_data: dict[str, Any],
    context: dict[str, Any],
    db: Any = None,
    shop_domain: str | None = None,
) -> dict[str, Any]:
    """
    Dispatch to the appropriate agent action.
    
    Args:
        action: The action name (e.g., "seo_optimize", "price_scout")
        product_data: Product data dict
        context: Additional context (e.g., request_id, target_locale)
        db: Optional SQLAlchemy session for usage tracking
        shop_domain: Optional shop domain for usage tracking
    """
    action = (action or "").strip()
    if action == "social_hook_architect":
        return social_hook_architect_action(product_data=product_data, context=context)
    if action == "seasonal_campaign_agent":
        return seasonal_campaign_agent_action(product_data=product_data, context=context)
    if action == "seasonal_campaign_caption":
        return seasonal_campaign_caption_action(product_data=product_data, context=context)
    if action == "value_discovery":
        return value_discovery_action(product_data=product_data, context=context)
    if action == "seo_optimize":
        return seo_optimize_action(product_data=product_data, context=context, db=db, shop_domain=shop_domain)
    if action == "price_scout":
        return price_scout_action(product_data=product_data, context=context, db=db, shop_domain=shop_domain)

    raise HTTPException(status_code=400, detail=f"Unknown action: {action}")


# ------------------------------------------------------------------------------
# Publish Action Map (Pro tier - called from POST /api/publish)
# Each handler is a thin async function that calls ShopifyService/MetaService.
# Signature: async handler(db, shop, content, product_id, context) -> dict | None
# ------------------------------------------------------------------------------

async def publish_seo_fields(*, db, shop, content, product_id, context, **kw):
    """Push SEO title + description → Shopify product SEO fields."""
    from src.ecommerce.services.shopify_service import update_product_seo, get_shop_credentials

    creds = get_shop_credentials(db, shop)
    if not creds.get("access_token"):
        raise ValueError("missing_credentials")

    # content can be a JSON string or dict
    import json as _json
    data = content
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except (ValueError, TypeError):
            data = {}
    if not isinstance(data, dict):
        data = {}

    seo_title = data.get("seo_title") or context.get("seo_title", "")
    seo_description = data.get("seo_description") or context.get("seo_description", "")
    if not seo_title and not seo_description:
        raise ValueError("seo_title or seo_description required")

    await update_product_seo(
        shop_domain=shop,
        access_token=creds["access_token"],
        product_id=product_id,
        seo_title=seo_title,
        seo_description=seo_description,
    )
    return None


async def publish_variant_price(*, db, shop, content, product_id, context, **kw):
    """Push recommended price → Shopify variant, with guardrails check."""
    from src.ecommerce.services.shopify_service import update_variant_price, get_shop_credentials

    creds = get_shop_credentials(db, shop)
    if not creds.get("access_token"):
        raise ValueError("missing_credentials")

    import json as _json
    data = content
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except (ValueError, TypeError):
            data = {}
    if not isinstance(data, dict):
        data = {}

    variant_id = context.get("variant_id") or data.get("variant_id")
    recommended_price = context.get("recommended_price") or data.get("recommended_price")
    if not variant_id or not recommended_price:
        raise ValueError("variant_id and recommended_price required")

    recommended_price = float(recommended_price)

    # Validate against guardrails
    guardrails = creds.get("price_guardrails") or {}
    min_price = guardrails.get("min_price", 0)
    max_price = guardrails.get("max_price", float("inf"))
    if not (min_price <= recommended_price <= max_price):
        raise ValueError(f"price_outside_guardrails: {recommended_price} not in [{min_price}, {max_price}]")

    await update_variant_price(
        shop_domain=shop,
        access_token=creds["access_token"],
        variant_id=variant_id,
        price=str(recommended_price),
    )
    return None


async def publish_meta_post(*, db, shop, content, product_id, context, **kw):
    """Push caption → Meta Graph API."""
    from src.ecommerce.services.shopify_service import get_shop_credentials
    from src.agentic_core.tools.meta_service import MetaService

    creds = get_shop_credentials(db, shop)
    meta_token = creds.get("meta_access_token")
    meta_page_id = creds.get("meta_page_id")
    if not meta_token or not meta_page_id:
        raise ValueError("meta_credentials_missing")

    caption = content if isinstance(content, str) else str(content or "")
    image_url = context.get("image_url")

    meta = MetaService()
    success, result = await meta.post_ad(
        page_id=meta_page_id,
        access_token=meta_token,
        caption=caption,
        image_url=image_url,
    )
    if not success:
        raise Exception(f"Meta post failed: {result}")
    return None


async def publish_flow_campaign(*, db, shop, content, product_id, context, **kw):
    """Push campaign data → Shopify Flow trigger."""
    from src.ecommerce.services.shopify_service import trigger_flow_event, get_shop_credentials

    creds = get_shop_credentials(db, shop)
    if not creds.get("access_token"):
        raise ValueError("missing_credentials")

    await trigger_flow_event(
        shop_domain=shop,
        access_token=creds["access_token"],
        event_topic="crossborder/seasonal-campaign",
        payload={
            "product_id": product_id or "",
            "content": content if isinstance(content, str) else str(content or ""),
        },
    )
    return None


async def publish_value_metafields(*, db, shop, content, product_id, context, **kw):
    """Push discovered values → Shopify product metafields."""
    from src.ecommerce.services.shopify_service import save_product_metafields, get_shop_credentials

    creds = get_shop_credentials(db, shop)
    if not creds.get("access_token"):
        raise ValueError("missing_credentials")
    if not product_id:
        raise ValueError("product_id required")

    import json as _json
    value = content if isinstance(content, str) else _json.dumps(content or [])

    await save_product_metafields(
        shop_domain=shop,
        access_token=creds["access_token"],
        product_id=product_id,
        metafields=[{
            "namespace": "crossborder_agent",
            "key": "value_discovery",
            "value": value,
            "type": "json",
        }],
    )
    return None


PUBLISH_ACTION_MAP: dict[str, Any] = {
    "seo_optimize": publish_seo_fields,
    "price_scout": publish_variant_price,
    "social_hook_architect": publish_meta_post,
    "seasonal_campaign_agent": publish_flow_campaign,
    "seasonal_campaign_caption": publish_meta_post,
    "value_discovery": publish_value_metafields,
}
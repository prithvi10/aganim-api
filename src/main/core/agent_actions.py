from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import os
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.main.logging.logger import get_logger
from src.main.service.open_ai_api_service import OpenAIService
from src.main.utils.llm_parser import parse_llm_json

logger = get_logger(__name__)
openai_service = OpenAIService()


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
@dataclass(frozen=True)
class Holiday:
    name: str
    date: date


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """
    weekday: Monday=0 ... Sunday=6
    n: 1..5
    """
    d = date(year, month, 1)
    days_ahead = (weekday - d.weekday()) % 7
    first = d + timedelta(days=days_ahead)
    return first + timedelta(days=7 * (n - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year + 1, 1, 1) - timedelta(days=1)
    days_back = (d.weekday() - weekday) % 7
    return d - timedelta(days=days_back)


def _us_holidays_for_year(year: int) -> list[Holiday]:
    thanksgiving = _nth_weekday_of_month(year, 11, weekday=3, n=4)  # Thu
    black_friday = thanksgiving + timedelta(days=1)
    cyber_monday = thanksgiving + timedelta(days=4)
    mothers_day = _nth_weekday_of_month(year, 5, weekday=6, n=2)  # Sun
    fathers_day = _nth_weekday_of_month(year, 6, weekday=6, n=3)  # Sun
    memorial_day = _last_weekday_of_month(year, 5, weekday=0)  # Mon
    labor_day = _nth_weekday_of_month(year, 9, weekday=0, n=1)  # Mon

    fixed = [
        Holiday("New Year’s Day", date(year, 1, 1)),
        Holiday("Valentine’s Day", date(year, 2, 14)),
        Holiday("Independence Day", date(year, 7, 4)),
        Holiday("Halloween", date(year, 10, 31)),
        Holiday("Christmas", date(year, 12, 25)),
    ]
    floating = [
        Holiday("Mother’s Day", mothers_day),
        Holiday("Memorial Day", memorial_day),
        Holiday("Father’s Day", fathers_day),
        Holiday("Labor Day", labor_day),
        Holiday("Thanksgiving", thanksgiving),
        Holiday("Black Friday", black_friday),
        Holiday("Cyber Monday", cyber_monday),
    ]
    return fixed + floating


def _next_upcoming_holiday(today: date) -> Holiday | None:
    candidates = _us_holidays_for_year(today.year) + _us_holidays_for_year(today.year + 1)
    candidates = [h for h in candidates if h.date >= today]
    candidates.sort(key=lambda h: h.date)
    return candidates[0] if candidates else None


def _discount_code_name(holiday_name: str, category: str, year: int) -> str:
    base = re.sub(r"[^A-Za-z0-9]", "", holiday_name).upper()
    cat = re.sub(r"[^A-Za-z0-9]", "", (category or "SALE")).upper()
    yy = str(year)[-2:]
    code = f"{base}{yy}{cat[:6]}"
    return code[:20]  # keep short-ish


# ------------------------------------------------------------------------------
# Agent actions
# ------------------------------------------------------------------------------
def social_hook_architect_action(product_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
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
        return {"text": "", "metadata": {"should_show": False}}

    days_until = (holiday.date - today).days
    should_show = days_until <= 42

    hashtags = _suggest_hashtags(product_title, category, tags if isinstance(tags, list) else None)
    discount_code = _discount_code_name(holiday.name, category, holiday.date.year)
    campaign_title = f"{holiday.name} {category} Campaign"

    use_ai = bool(os.getenv("OPENAI_API_KEY"))
    caption = ""

    if use_ai and product_title:
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


def run_agent_action(action: str, product_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = (action or "").strip()
    if action == "social_hook_architect":
        return social_hook_architect_action(product_data=product_data, context=context)
    if action == "seasonal_campaign_agent":
        return seasonal_campaign_agent_action(product_data=product_data, context=context)
    if action == "seasonal_campaign_caption":
        return seasonal_campaign_caption_action(product_data=product_data, context=context)

    raise HTTPException(status_code=400, detail=f"Unknown action: {action}")



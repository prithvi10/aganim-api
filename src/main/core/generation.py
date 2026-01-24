import os
import httpx
import asyncio
from fastapi import HTTPException
from sqlalchemy.orm import Session
import json
from src.main.db.db_models import User
from src.main.api.models import RewriteRequest, BulkRewriteRequest
from src.main.service.open_ai_api_service import OpenAIService
from src.main.service import serp_service
from src.main.security.ratelimiter import InMemoryRateLimiter
from src.main.config.configs import (
    LOCAL_RATE_LIMIT_CONFIG,
    LOCALE_PERSONA_MAP,
    OPENAI_MODEL,
)
from src.main.config.prompts import (
    SYSTEM_PROMPT,
    TONE_PROMPTS,
    VALUE_DISCOVERY_PROMPT,
    SPEC_TABLES_TECH_PASS_SYSTEM_TEMPLATE,
    SEO_RECOMMENDATIONS_TECH_PASS_SYSTEM_TEMPLATE,
)
from src.main.utils.text_processor import detect_and_label_sections
from src.main.utils.llm_parser import parse_llm_json, recover_title_desc
from src.main.logging.logger import get_logger
from src.main.db.db_transactions import get_shop_access_token
from src.main.service.shopify_service import save_product_content_with_locale
from src.main.api.validation import validate_rewrite_request
from src.main.service.fair_use import get_base_model_for_shop, get_effective_model, record_cost_from_usage

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
    def _normalize_category(cat: object) -> str:
        s = str(cat or "").strip()
        if not s:
            return ""
        # Some models output "A | B" even when asked for one. Take the first segment.
        if "|" in s:
            s = s.split("|", 1)[0].strip()
        sl = s.lower()
        # Accept a few common near-misses.
        alias = {
            "artisan mastery": "Artisan Master",
            "artisan master": "Artisan Master",
            "time as luxury": "Time-as-Luxury",
            "time-as-luxury": "Time-as-Luxury",
            "tactile and sensory": "Tactile & Sensory",
            "tactile & sensory": "Tactile & Sensory",
            "regional pedigree": "Regional Pedigree",
        }
        if sl in alias:
            return alias[sl]
        # Case-insensitive exact match to allowed set
        for allowed in ALLOWED_DISCOVERY_CATEGORIES:
            if sl == allowed.lower():
                return allowed
        return s

    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        category = _normalize_category(item.get("category"))
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


def _parse_model_json(raw_content: str) -> tuple[dict, list[dict], dict]:
    """
    Parses LLM output. Preferred schema (contract-safe):
      { "title": "...", "description": "...", "seo_title": "...", "seo_description": "...", "discovered_values": [...] }
    Back-compat:
      { "rewritten_description": "...", "discovered_values": [...] }
    """
    parsed = parse_llm_json(raw_content)
    meta: dict = {
        "parse_mode": "none",
        "raw_len": len(raw_content or ""),
        "raw_discovered_count": None,
    }
    if isinstance(parsed, dict):
        meta["raw_discovered_count"] = (
            len(parsed.get("discovered_values") or [])
            if isinstance(parsed.get("discovered_values"), list)
            else None
        )

    # Contract-safe schema: title + description + optional discovered_values
    if isinstance(parsed, dict) and (
        isinstance(parsed.get("title"), str) or isinstance(parsed.get("description"), str)
    ):
        meta["parse_mode"] = "json_contract"
        discovered_values = _normalize_discovered_values(parsed.get("discovered_values"))
        data = {
            "title": str(parsed.get("title") or "").strip(),
            "description": str(parsed.get("description") or "").strip(),
            "seo_title": str(parsed.get("seo_title") or "").strip(),
            "seo_description": str(parsed.get("seo_description") or "").strip(),
            "seo_alt_text": str(parsed.get("seo_alt_text") or "").strip(),
            "misc_information": str(parsed.get("misc_information") or "").strip(),
            "seo_insights": parsed.get("seo_insights") if isinstance(parsed.get("seo_insights"), dict) else {},
        }
        if not data["description"]:
            data["description"] = raw_content
        return data, discovered_values, meta

    # Back-compat schema: rewritten_description + optional discovered_values
    if isinstance(parsed, dict) and isinstance(parsed.get("rewritten_description"), str):
        meta["parse_mode"] = "json_legacy"
        discovered_values = _normalize_discovered_values(parsed.get("discovered_values"))
        data = {
            "title": "",
            "description": parsed.get("rewritten_description") or "",
            "seo_title": str(parsed.get("seo_title") or "").strip(),
            "seo_description": str(parsed.get("seo_description") or "").strip(),
            "seo_alt_text": str(parsed.get("seo_alt_text") or "").strip(),
            "misc_information": str(parsed.get("misc_information") or "").strip(),
            "seo_insights": parsed.get("seo_insights") if isinstance(parsed.get("seo_insights"), dict) else {},
        }
        if not data["description"]:
            data["description"] = raw_content
        return data, discovered_values, meta

    legacy = parsed if isinstance(parsed, dict) else None
    legacy = legacy or recover_title_desc(raw_content)
    if isinstance(legacy, dict):
        meta["parse_mode"] = "recover_title_desc"
        return (
            {
                "title": str(legacy.get("title") or ""),
                "description": str(legacy.get("description") or raw_content),
                "seo_title": str(legacy.get("seo_title") or ""),
                "seo_description": str(legacy.get("seo_description") or ""),
                "seo_alt_text": str(legacy.get("seo_alt_text") or ""),
                "misc_information": str(legacy.get("misc_information") or "").strip(),
                "seo_insights": legacy.get("seo_insights") if isinstance(legacy.get("seo_insights"), dict) else {},
            },
            [],
            meta,
        )

    meta["parse_mode"] = "raw_fallback"
    return (
        {
            "title": "",
            "description": raw_content,
            "seo_title": "",
            "seo_description": "",
            "seo_alt_text": "",
            "misc_information": "",
            "seo_insights": {},
        },
        [],
        meta,
    )


def _log_llm_contract_health(
    *,
    shop: str,
    target_locale: str,
    meta: dict,
    parsed: dict,
    discovered_values: list[dict],
) -> None:
    """
    Logs contract/shape health without logging any model content.
    Intended for diagnosing why SEO or discovered_values might be missing.
    """
    try:
        title_present = bool(str(parsed.get("title") or "").strip())
        seo_title_present = bool(str(parsed.get("seo_title") or "").strip())
        seo_desc_present = bool(str(parsed.get("seo_description") or "").strip())
        seo_alt_present = bool(str(parsed.get("seo_alt_text") or "").strip())
        desc_len = len(str(parsed.get("description") or ""))

        missing = []
        if not title_present:
            missing.append("title")
        if desc_len <= 0:
            missing.append("description")
        if not seo_title_present:
            missing.append("seo_title")
        if not seo_desc_present:
            missing.append("seo_description")
        if not seo_alt_present:
            missing.append("seo_alt_text")

        logger.debug(
            "[LLMContract] shop=%s locale=%s parse=%s raw_len=%s title=%s desc_len=%s seo_title=%s seo_desc=%s discovered_raw=%s discovered_ok=%s missing=%s",
            shop,
            target_locale,
            meta.get("parse_mode"),
            meta.get("raw_len"),
            title_present,
            desc_len,
            seo_title_present,
            seo_desc_present,
            meta.get("raw_discovered_count"),
            len(discovered_values or []),
            ",".join(missing) if missing else "-",
        )

        # Escalate when we likely won't be able to render SEO/insights in UI.
        if missing or meta.get("parse_mode") in ("recover_title_desc", "raw_fallback"):
            logger.warning(
                "[LLMContract] missing_fields shop=%s locale=%s parse=%s missing=%s discovered_ok=%s",
                shop,
                target_locale,
                meta.get("parse_mode"),
                ",".join(missing) if missing else "-",
                len(discovered_values or []),
            )
    except Exception:
        # Never let logging break generation.
        return


def _should_log_llm_full(shop: str) -> bool:
    """
    Full LLM logging is sensitive. Only enable when explicitly requested via env flags.
    - LOG_LLM_FULL=1 enables
    - LOG_LLM_SHOP=<shop-domain> optionally restricts to a single shop
    """
    if os.getenv("LOG_LLM_FULL", "").strip() != "1":
        return False
    only = (os.getenv("LOG_LLM_SHOP", "") or "").strip().lower()
    if only and only != str(shop or "").strip().lower():
        return False
    return True


async def _fetch_primary_locale(shop: str, access_token: str | None) -> str:
    primary_locale = "en"
    if not access_token:
        return primary_locale
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://{shop}/admin/api/2024-07/shop.json",
                headers={"X-Shopify-Access-Token": access_token},
            )
            if resp.status_code == 200:
                primary_locale = resp.json().get("shop", {}).get("primary_locale", "en")
    except Exception:
        pass
    return primary_locale


def _log_llm_full_response(
    *,
    shop: str,
    target_locale: str,
    raw_content: str,
    parsed: dict,
    discovered_values: list[dict],
    meta: dict,
) -> None:
    """
    Logs FULL raw + parsed LLM response.
    WARNING: This may contain merchant content. Use LOG_LLM_FULL=1 and LOG_LLM_SHOP to scope.
    """
    try:
        logger.warning(
            "[LLMFull] BEFORE_PARSE shop=%s locale=%s parse=%s raw_len=%s\n-----BEGIN_LLM_RAW-----\n%s\n-----END_LLM_RAW-----",
            shop,
            target_locale,
            meta.get("parse_mode"),
            meta.get("raw_len"),
            raw_content or "",
        )
        logger.warning(
            "[LLMFull] AFTER_PARSE shop=%s locale=%s discovered_ok=%s\n-----BEGIN_LLM_PARSED-----\n%s\n-----END_LLM_PARSED-----",
            shop,
            target_locale,
            len(discovered_values or []),
            json.dumps(parsed or {}, ensure_ascii=False),
        )
        logger.warning(
            "[LLMFull] AFTER_NORMALIZATION shop=%s locale=%s\n-----BEGIN_LLM_DISCOVERED_VALUES-----\n%s\n-----END_LLM_DISCOVERED_VALUES-----",
            shop,
            target_locale,
            json.dumps(discovered_values or [], ensure_ascii=False),
        )
    except Exception:
        return


def _missing_seo_fields(parsed: dict) -> bool:
    return (
        not bool(str(parsed.get("seo_title") or "").strip())
        or not bool(str(parsed.get("seo_description") or "").strip())
        or not bool(str(parsed.get("seo_alt_text") or "").strip())
    )


def _augment_seo_and_discoveries_if_missing(
    *,
    db: Session,
    shop: str,
    target_locale: str,
    product_name: str,
    category: str,
    processed_description: str,
    parsed: dict,
    discovered_values: list[dict],
    model_used: str,
    parse_meta: dict,
) -> tuple[dict, list[dict]]:
    """
    If the primary generation response was truncated or missing SEO/insights, run a small,
    contract-focused follow-up call to fetch ONLY: seo_title, seo_description, seo_alt_text, discovered_values.
    """
    try:
        need = _missing_seo_fields(parsed) or parse_meta.get("parse_mode") in ("recover_title_desc", "raw_fallback")
        if not need:
            return parsed, discovered_values

        logger.warning(
            "[LLMContract] self_heal_missing shop=%s locale=%s parse=%s missing=%s discovered_ok=%s",
            shop,
            target_locale,
            parse_meta.get("parse_mode"),
            "seo_title,seo_description,seo_alt_text" if _missing_seo_fields(parsed) else "-",
            len(discovered_values or []),
        )

        system = f"""You are a Senior E-commerce Growth Copywriter.

Return ONLY valid JSON with this exact shape:
{{
  "seo_title": "...",
  "seo_description": "...",
  "seo_alt_text": "...",
  "discovered_values": [
    {{
      "category": "Regional Pedigree | Tactile & Sensory | Time-as-Luxury | Artisan Master",
      "evidence": "Japanese snippet proving the value",
      "explanation": "One sentence in professional English explaining why this matters to Western customers.",
      "suggested_footer": "A professional English paragraph to add to the description."
    }}
  ]
}}

Rules:
- Output language for seo_title/seo_description must match TARGET LANGUAGE: {target_locale}
- Output language for seo_alt_text must match TARGET LANGUAGE: {target_locale}
- Evidence must quote a short Japanese snippet from the source.
- Categories MUST be one of: Regional Pedigree, Tactile & Sensory, Time-as-Luxury, Artisan Master.
- If there is no clear evidence, return discovered_values: [].
""".strip()

        user = {
            "product_name": product_name,
            "category": category,
            "target_locale": target_locale,
            "japanese_description": processed_description,
        }

        heal_raw = openai_service.generate_json(
            system_prompt=system, user_json=user, temperature=0.2, max_tokens=700
        )
        if _should_log_llm_full(shop):
            logger.warning(
                "[LLMFull] HEAL_BEFORE_PARSE shop=%s locale=%s raw_len=%s\n-----BEGIN_LLM_RAW-----\n%s\n-----END_LLM_RAW-----",
                shop,
                target_locale,
                len(heal_raw or ""),
                heal_raw or "",
            )
        healed = parse_llm_json(heal_raw or "")
        if not isinstance(healed, dict):
            healed = {}

        seo_title = str(healed.get("seo_title") or "").strip()
        seo_desc = str(healed.get("seo_description") or "").strip()
        seo_alt = str(healed.get("seo_alt_text") or "").strip()
        if seo_title:
            parsed["seo_title"] = seo_title
        if seo_desc:
            parsed["seo_description"] = seo_desc
        if seo_alt:
            parsed["seo_alt_text"] = seo_alt

        healed_values = _normalize_discovered_values(healed.get("discovered_values"))
        if healed_values:
            discovered_values = healed_values

        if _should_log_llm_full(shop):
            logger.warning(
                "[LLMFull] HEAL_AFTER_PARSE shop=%s locale=%s\n-----BEGIN_LLM_PARSED-----\n%s\n-----END_LLM_PARSED-----",
                shop,
                target_locale,
                json.dumps(
                    {
                        "seo_title": parsed.get("seo_title"),
                        "seo_description": parsed.get("seo_description"),
                        "seo_alt_text": parsed.get("seo_alt_text"),
                        "discovered_values": discovered_values,
                    },
                    ensure_ascii=False,
                ),
            )

        return parsed, discovered_values
    except Exception as e:
        logger.warning("[LLMContract] self_heal_failed shop=%s locale=%s err=%s", shop, target_locale, e)
        return parsed, discovered_values


def _is_english_locale(locale: str | None) -> bool:
    if not locale:
        return False
    return str(locale).strip().lower().startswith("en")

def _effective_tone(plan_name: str | None, requested: str | None) -> str:
    """
    Basic plan: force professional.
    Standard/Pro: allow requested tone if known; otherwise default to professional.
    """
    # (keep it simple and robust for mocked plans)
    name = str(plan_name or "").strip().lower()
    if name == "basic":
        return "professional"
    tone = str(requested or "").strip().lower()
    return tone if tone in TONE_PROMPTS else "professional"


def _build_dynamic_prompt(
    target_locale: str,
    *,
    auto_convert_units: bool = False,
    tone_profile: str = "professional",
    plan_name: str | None = None,
    brand_name: str | None = None,
    remove_irrelevant_content: bool = True,
) -> str:
    market_persona = LOCALE_PERSONA_MAP.get(target_locale, "Global English Market")
    pname = str(plan_name or "").strip().lower()
    brand = str(brand_name or "").strip()
    unit_conversion_block = ""
    if auto_convert_units and _is_english_locale(target_locale):
        unit_conversion_block = """

UNIT CONVERSION (STRICT, ENGLISH ONLY):
- Scan the SOURCE text for metric measurements: cm, mm, m, g, kg, ml, L (including variants like "10 cm", "10cm", "10㎝").
- In the ENGLISH output, ALWAYS KEEP the original metric measurement and append the US Customary equivalent in parentheses immediately after it.
- Never remove or replace the metric value. Japanese brands often require original specs for accuracy.
- Use "approx." and sensible rounding (typically 0–1 decimals). Choose the most natural US unit (in/ft/oz/lb/fl oz) per context.
"""
    tone_block = f"""

TONE INSTRUCTION (DYNAMIC):
{TONE_PROMPTS.get(tone_profile, TONE_PROMPTS.get("professional", ""))}

FACT ACCURACY (STRICT):
- Regardless of tone, keep core product facts 100% accurate (dimensions, materials, capacities, provenance).
- Do NOT invent measurements, materials, certifications, or historical claims not present in the source text.
""".rstrip()
    value_discovery_block = f"""

{VALUE_DISCOVERY_PROMPT}
""".rstrip()
    seo_block = f"""

SEO METADATA (STRICT):
- Generate locale-specific SEO metadata for TARGET LANGUAGE ({target_locale}) and MARKET PERSONA ({market_persona}).
- Use high-volume keywords relevant to that target market, but do NOT invent product facts/specs/certifications/provenance.

SEO TITLE (<= 70 chars):
- Lead with the most important keyword + clear product type.
- Keep it readable; remove filler if near the limit.

SEO META DESCRIPTION (<= 160 chars) — MUST satisfy PST:
- (PST Check) Start with ONE short problem/question or desire (P).
- (Solution) Follow with a concrete benefit tied to a real product fact (S).
- (Brand Trust) Add ONE trust cue ONLY if supported by the source text (e.g., made in Japan, artisan-crafted, region/provenance, traditional method, free shipping if present).
- End with a simple CTA.
- Avoid keyword stuffing and avoid repeating the SEO title verbatim.

seo_alt_text:
- Generate a descriptive, keyword-relevant alt tag for the MAIN product image (no quotes needed).
""".rstrip()

    serp_insights_block = ""
    if pname in ("standard", "pro"):
        serp_insights_block = f"""

### SEO INSIGHTS (STANDARD TIER):
- Benchmarking: Analyze the provided competitor_context.
- You must identify and naturally inject 5-8 high-density keywords (LSI) used by the Top 3 Google winners.
- Return a JSON object containing the description and an seo_insights object with:
  - lsi_keywords_used (list)
  - search_intent (Transactional or Informational)
  - competitive_edge (one unique Japanese detail competitors missed)
""".rstrip()

    spec_tables_handoff_block = ""
    if pname in ("standard", "pro"):
        spec_tables_handoff_block = """

### SPEC TABLES HANDOFF (STANDARD/PRO):
- IMPORTANT: Do NOT generate any specification/dimensions tables in the main description.
- Do NOT create sections titled: "Specifications", "Product Specifications", "Detailed Dimensions", "Specs", or "仕様".
- If the source contains specs (capacity/material/compatibility) mention them briefly as plain text or simple bullets inside existing narrative sections (no <table>).
- The system will generate the Product Specifications + Detailed Dimensions tables in a separate technical pass.
""".rstrip()

    if pname == "basic":
        seo_block = f"""

### SEO & CTR ENGINEERING (BASIC TIER):
- **SEO Title (<= 70 chars):**
  - Format: [Primary Keyword] | [Key Benefit/Unique Value] | [Brand Name]
  - Strategy: Lead with the most important keyword.
  - Brand Name: Use "{brand}" when appropriate; if it would harm clarity or exceed length, omit it.
- **SEO Description (<= 160 chars):**
  - Use the **PST Formula**: (1) State a specific **Problem** or desire, (2) Present the product as the **Solution**, (3) End with ONE **Trust** signal/CTA ONLY if supported by source text (made in Japan, artisan, provenance, shipping).
  - Example style: "Tired of mass-produced tea? (P) Discover handcrafted Uji Matcha (S). Direct from Japan—shop now. (T)"
- **Image Alt-Text (seo_alt_text) (NEW):**
  - Generate a descriptive, keyword-rich Alt-tag for the main product image.
  - Format: "[Color/Style] [Material] [Product Type] - [Key Feature]"
""".rstrip()

    misc_block = """

MISC / NON-PRODUCT CONTENT HANDLING:
- Identify any non-product or administrative content (e.g., SEO/meta drafts, multilingual notes, hashtags, logistics/returns blocks, shipping disclaimers, metadata blobs).
- {misc_action}
- Keep ALL misc content out of title, description, seo_title, seo_description, and seo_alt_text.
- NEVER include hashtags anywhere in the output.
""".format(
        misc_action=(
            "Remove ALL misc/non-product content entirely from the output. Do NOT emit it in any field."
            if remove_irrelevant_content
            else "Move ALL misc/non-product content into a dedicated field `misc_information` as concise bullets, and keep it OUT of title/description/SEO fields."
        )
    ).rstrip()

    pst_block = """

CTR / PST GUARDRAIL (ALL TIERS):
- The description MUST contain: (P) one sentence with a question/pain point or desire, (S) a concrete benefit with a key spec, (T) a CTA or trust cue. If missing in source, add them.
- Keep it concise and high-conversion; avoid vague or generic phrasing.
- Do NOT repeat SEO title/description inside the product description.
- If misc content (SEO/meta/multilingual notes/hashtags/logistics) appears in source, handle it according to the MISC block above.
""".rstrip()

    return f"""{SYSTEM_PROMPT}

TARGET LANGUAGE: {target_locale}
MARKET PERSONA: {market_persona}
BRAND NAME: {brand or "N/A"}

ADDITIONAL LOCALIZATION RULES:
- Write both "title" and "description" in the TARGET LANGUAGE ({target_locale}) only.
- Use local idioms and market-specific triggers for {market_persona}. Avoid literal English/Japanese if not the target.
- For zh-TW: prefer Taiwanese Mandarin expressions and highlight CP値/CP ratio.
- For ko: keep tone natural for Korean shoppers.
- Keep JSON shape exactly:
  {{"title": "...", "description": "...", "seo_title": "...", "seo_description": "...", "seo_alt_text": "...", "misc_information": "...", "seo_insights": {{"lsi_keywords_used": [...], "search_intent": "...", "competitive_edge": "..."}}, "discovered_values": [...]}}.
- Only extract values for which there is clear evidence in the text. Do not hallucinate or add history for crafts not mentioned.
{seo_block}
{serp_insights_block}
{spec_tables_handoff_block}
{pst_block}
{misc_block}

SECTION TAGS:
- The Japanese input may include [Section: LABEL] ... [/Section] markers. Preserve order. For each Section, create a distinct <h3> with that LABEL. Do not merge sections. Use <hr /> between major section groups if needed.
{unit_conversion_block}
{tone_block}
{value_discovery_block}
"""

def _sanitize_html_for_json_fields(data: dict) -> dict:
    """
    Normalize double quotes inside HTML strings so JSON packing never breaks when the
    model emits attributes like <div class="table">. Converts double quotes to single
    quotes for known HTML-bearing fields.
    """
    if not isinstance(data, dict):
        return data
    html_fields = ("description", "seo_title", "seo_description", "seo_alt_text", "misc_information")
    for key in html_fields:
        val = data.get(key)
        if isinstance(val, str) and '"' in val:
            data[key] = val.replace('"', "'")
    return data


def _augment_spec_tables_for_standard_pro(
    *,
    db: Session,
    shop: str,
    target_locale: str,
    description_html: str,
    source_text: str,
    auto_convert_units: bool,
) -> str:
    """
    Standard/Pro-only technical correction pass:
    - Generate Product Specifications + Detailed Dimensions HTML tables
    - Append them to the existing description HTML
    - Ensure no duplicate tables

    IMPORTANT: We intentionally keep this separate from the main generation prompt
    to reduce prompt complexity and improve table accuracy.
    """
    system = SPEC_TABLES_TECH_PASS_SYSTEM_TEMPLATE.format(target_locale=target_locale)

    user = {
        "target_locale": target_locale,
        "auto_convert_units": bool(auto_convert_units),
        "description_html": str(description_html or ""),
        "source_text": str(source_text or ""),
    }

    try:
        logger.info(
            "[SpecTables] start shop=%s locale=%s model=%s desc_len=%s source_len=%s auto_convert_units=%s",
            shop,
            target_locale,
            OPENAI_MODEL,
            len(str(description_html or "")),
            len(str(source_text or "")),
            bool(auto_convert_units),
        )
    except Exception:
        pass

    raw = openai_service.generate_json(
        system_prompt=system,
        user_json=user,
        temperature=0.0,
        max_tokens=1100,
        # Force cheapest model for this technical pass (Standard/Pro only).
        model=OPENAI_MODEL,
    )

    if _should_log_llm_full(shop):
        try:
            logger.warning(
                "[LLMFull] SPEC_TABLES_BEFORE_PARSE shop=%s locale=%s raw_len=%s\n-----BEGIN_LLM_RAW-----\n%s\n-----END_LLM_RAW-----",
                shop,
                target_locale,
                len(raw or ""),
                raw or "",
            )
        except Exception:
            pass

    parsed = parse_llm_json(raw or "")
    if not isinstance(parsed, dict):
        logger.warning(
            "[SpecTables] parse_failed shop=%s locale=%s raw_len=%s",
            shop,
            target_locale,
            len(raw or ""),
        )
        return str(description_html or "")

    final_html = str(parsed.get("final_description_html") or "").strip()
    specs_tbl = str(parsed.get("product_specifications_table_html") or "").strip()
    dims_tbl = str(parsed.get("detailed_dimensions_table_html") or "").strip()
    removed_tables_count = parsed.get("removed_tables_count")
    try:
        removed_tables_count = int(removed_tables_count) if removed_tables_count is not None else None
    except Exception:
        removed_tables_count = None

    def _strip_existing_spec_dim_tables(html: str) -> str:
        """
        Remove previously-inserted Product Specifications / Detailed Dimensions blocks.
        Conservative: only strips when it sees the exact <h3> headers and a following <table>.
        """
        import re

        out = str(html or "")
        patterns = [
            r"<h3>\s*Product Specifications\s*</h3>\s*<table[\s\S]*?</table>",
            r"<h3>\s*Detailed Dimensions\s*</h3>\s*<table[\s\S]*?</table>",
        ]
        for pat in patterns:
            out = re.sub(pat, "", out, flags=re.IGNORECASE)
        return out.strip()

    def _extract_table_block(html: str, heading: str) -> str:
        """
        Extract a '<h3>HEADING</h3> + <table>...</table>' block from html.
        Returns empty string if not found.
        """
        import re

        s = str(html or "")
        pat = rf"(<h3>\s*{re.escape(heading)}\s*</h3>\s*<table[\s\S]*?</table>)"
        m = re.search(pat, s, flags=re.IGNORECASE)
        return str(m.group(1)).strip() if m else ""

    # We accept either:
    # - a fully-merged final_description_html that already contains the tables, OR
    # - split table fields we can append ourselves.
    final_has_any_table = "<table" in final_html.lower()
    final_has_specs = "<h3>Product Specifications</h3>" in final_html
    final_has_dims = "<h3>Detailed Dimensions</h3>" in final_html

    specs_block = ""
    dims_block = ""

    # Prefer explicit split fields if present; otherwise try extracting from final_html.
    if "<table" in (specs_tbl or "").lower():
        specs_block = specs_tbl
    else:
        specs_block = _extract_table_block(final_html, "Product Specifications")

    if "<table" in (dims_tbl or "").lower():
        dims_block = dims_tbl
    else:
        dims_block = _extract_table_block(final_html, "Detailed Dimensions")

    # Ensure headings exist (some models might return bare <table>...</table>)
    if specs_block and "<h3" not in specs_block.lower():
        specs_block = f"<h3>Product Specifications</h3>\n{specs_block}".strip()
    if dims_block and "<h3" not in dims_block.lower():
        dims_block = f"<h3>Detailed Dimensions</h3>\n{dims_block}".strip()

    has_specs = "<h3>Product Specifications</h3>" in specs_block
    has_dims = "<h3>Detailed Dimensions</h3>" in dims_block

    try:
        logger.info(
            "[SpecTables] parsed shop=%s locale=%s raw_len=%s final_len=%s final_has_table=%s final_has_specs=%s final_has_dims=%s specs_len=%s dims_len=%s has_specs=%s has_dims=%s removed_tables_count=%s",
            shop,
            target_locale,
            len(raw or ""),
            len(final_html or ""),
            bool(final_has_any_table),
            bool(final_has_specs),
            bool(final_has_dims),
            len(specs_block or ""),
            len(dims_block or ""),
            bool(has_specs),
            bool(has_dims),
            removed_tables_count,
        )
    except Exception:
        pass

    # Minimal validation: if we don't have BOTH tables, keep original description.
    if not (has_specs and has_dims):
        logger.warning(
            "[SpecTables] invalid_final_html shop=%s locale=%s final_len=%s specs_len=%s dims_len=%s",
            shop,
            target_locale,
            len(final_html or ""),
            len(specs_block or ""),
            len(dims_block or ""),
        )
        return str(description_html or "")

    # Deterministic merge (prevents accidental prose edits and avoids trusting malformed final_html).
    base = _strip_existing_spec_dim_tables(description_html)
    append = "\n\n<hr />\n" + specs_block.strip() + "\n\n" + dims_block.strip()
    merged = (base.rstrip() + append).strip()

    if _should_log_llm_full(shop):
        try:
            logger.warning(
                "[LLMFull] SPEC_TABLES_AFTER_PARSE shop=%s locale=%s\n-----BEGIN_LLM_PARSED-----\n%s\n-----END_LLM_PARSED-----",
                shop,
                target_locale,
                json.dumps(parsed or {}, ensure_ascii=False),
            )
        except Exception:
            pass

    return merged or str(description_html or "")


def _generate_seo_recommendations(
    *,
    db: Session,
    shop: str,
    target_locale: str,
    product_name: str,
    category: str,
    description_html: str,
    seo_title: str,
    seo_description: str,
) -> dict | None:
    """
    Cheap, always-on (all plans) technical recommendation pass executed during Optimize.
    Returns a JSON dict to attach under `seo_recommendations` in the generation response.
    Never raises.
    """
    try:
        # NOTE: This prompt contains literal JSON braces; avoid `.format(...)` to prevent KeyError.
        system = str(SEO_RECOMMENDATIONS_TECH_PASS_SYSTEM_TEMPLATE).replace("{target_locale}", str(target_locale))
        user = {
            "product_name": str(product_name or "").strip(),
            "category": str(category or "").strip(),
            "target_locale": str(target_locale or "").strip(),
            "description_html": str(description_html or ""),
            "seo_title": str(seo_title or ""),
            "seo_description": str(seo_description or ""),
        }

        logger.info(
            "[SEORecs] start shop=%s locale=%s model=%s desc_len=%s seo_title_len=%s seo_desc_len=%s",
            shop,
            target_locale,
            OPENAI_MODEL,
            len(str(description_html or "")),
            len(str(seo_title or "")),
            len(str(seo_description or "")),
        )

        resp = openai_service.generate_json_response(
            system_prompt=system,
            user_json=user,
            temperature=0.0,
            max_tokens=900,
            model=OPENAI_MODEL,
        )

        # Cost accounting (best-effort)
        try:
            record_cost_from_usage(db, shop, getattr(resp, "usage", None), model_used=OPENAI_MODEL)
        except Exception as e:
            logger.warning(f"[SEORecs] cost_accounting_skipped shop={shop}: {e}")

        raw = ""
        try:
            raw = resp.choices[0].message.content or ""
        except Exception:
            raw = ""

        if _should_log_llm_full(shop):
            try:
                logger.warning(
                    "[LLMFull] SEO_RECS_BEFORE_PARSE shop=%s locale=%s raw_len=%s\n-----BEGIN_LLM_RAW-----\n%s\n-----END_LLM_RAW-----",
                    shop,
                    target_locale,
                    len(raw or ""),
                    raw or "",
                )
            except Exception:
                pass

        parsed = parse_llm_json(raw or "")
        if not isinstance(parsed, dict):
            logger.warning("[SEORecs] parse_failed shop=%s locale=%s raw_len=%s", shop, target_locale, len(raw or ""))
            return None

        # Minimal shape validation (keep permissive; UI will be defensive)
        edge = parsed.get("competitive_edge") if isinstance(parsed.get("competitive_edge"), dict) else {}
        buyer = parsed.get("buyer_intent") if isinstance(parsed.get("buyer_intent"), dict) else {}

        out = {
            "competitive_edge": {
                "headline": str(edge.get("headline") or "").strip(),
                "copy": str(edge.get("copy") or "").strip(),
            },
            "buyer_intent": {
                "strategy": buyer.get("strategy") if isinstance(buyer.get("strategy"), list) else [],
            },
        }

        logger.info(
            "[SEORecs] ok shop=%s locale=%s has_edge=%s buyer_intent_bullets=%s",
            shop,
            target_locale,
            bool(out["competitive_edge"].get("copy") or out["competitive_edge"].get("headline")),
            len(out["buyer_intent"].get("strategy") or []),
        )

        if _should_log_llm_full(shop):
            try:
                logger.warning(
                    "[LLMFull] SEO_RECS_AFTER_PARSE shop=%s locale=%s\n-----BEGIN_LLM_PARSED-----\n%s\n-----END_LLM_PARSED-----",
                    shop,
                    target_locale,
                    json.dumps(out or {}, ensure_ascii=False),
                )
            except Exception:
                pass

        return out
    except Exception as e:
        logger.warning("[SEORecs] failed shop=%s locale=%s err=%s", shop, target_locale, e)
        return None


def _clamp_len(s: str, max_len: int) -> str:
    """
    Clamp a string to max_len characters, preferring to cut at a word boundary when possible.
    Deterministic post-processing to enforce SEO length constraints.
    """
    text = str(s or "").strip()
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rstrip()
    # Prefer last whitespace boundary if it keeps at least 60% of the budget.
    idx = cut.rfind(" ")
    if idx >= int(max_len * 0.6):
        cut = cut[:idx].rstrip()
    return cut

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
    *,
    auto_convert_units: bool = False,
    tone_profile: str = "professional",
    plan_name: str | None = None,
    competitor_context: list[dict] | None = None,
    remove_irrelevant_content: bool = True,
):
    """
    Helper to generate copy for a single locale and save it to Shopify.
    """
    dynamic_prompt = _build_dynamic_prompt(
        target_locale,
        auto_convert_units=auto_convert_units,
        tone_profile=tone_profile,
        # Use canonical plan name for SEO tiering (Basic gets PST + specific formats).
        plan_name=plan_name,
        brand_name=str(shop or "").replace(".myshopify.com", ""),
        remove_irrelevant_content=remove_irrelevant_content,
    )

    base_model = get_base_model_for_shop(db, shop)
    model_override = get_effective_model(db, shop, base_model)
    
    openai_response = openai_service.generate_copy(
        product_name=product_name,
        category=category,
        japanese_description=processed_description,
        system_prompt=dynamic_prompt,
        model=model_override,
        competitor_context=competitor_context,
    )

    # Internal-only cost accounting + fair-use monitoring (never blocks)
    try:
        usage = getattr(openai_response, "usage", None)
        record_cost_from_usage(db, shop, usage, model_used=model_override)
    except Exception as e:
        logger.warning(f"[FairUse] Cost accounting skipped for shop={shop}: {e}")

    raw_content = openai_response.choices[0].message.content
    parsed, discovered_values, parse_meta = _parse_model_json(raw_content or "")
    parsed = _sanitize_html_for_json_fields(parsed)
    competitor_titles: list[str] = []
    competitor_results: list[dict] = []
    if isinstance(competitor_context, list):
        for item in competitor_context:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            link = str(item.get("link") or "").strip()
            if title or snippet or link:
                competitor_results.append(
                    {"title": title or None, "snippet": snippet or None, "link": link or None}
                )
        competitor_results = competitor_results[:3]
        competitor_titles = [str(r.get("title") or "").strip() for r in competitor_results if r.get("title")]
    _log_llm_contract_health(
        shop=shop,
        target_locale=target_locale,
        meta=parse_meta,
        parsed=parsed,
        discovered_values=discovered_values,
    )
    try:
        logger.debug(
            "[LLMPrompt] shop=%s locale=%s plan=%s prompt_snippet=%s",
            shop,
            target_locale,
            plan_name,
            (dynamic_prompt[:1200] + "...") if len(dynamic_prompt) > 1200 else dynamic_prompt,
        )
    except Exception:
        pass
    if _should_log_llm_full(shop):
        _log_llm_full_response(
            shop=shop,
            target_locale=target_locale,
            raw_content=raw_content or "",
            parsed=parsed,
            discovered_values=discovered_values,
            meta=parse_meta,
        )
    parsed, discovered_values = _augment_seo_and_discoveries_if_missing(
        db=db,
        shop=shop,
        target_locale=target_locale,
        product_name=product_name,
        category=category,
        processed_description=processed_description,
        parsed=parsed,
        discovered_values=discovered_values,
        model_used=model_override,
        parse_meta=parse_meta,
    )
    # Preserve existing contract: always return a title string to clients.
    if not str(parsed.get("title") or "").strip():
        parsed["title"] = product_name or "Generated Copy"
    if not str(parsed.get("description") or "").strip():
        parsed["description"] = raw_content or ""
    # Standard/Pro: generate specs + dimensions tables in a separate, cheap technical pass.
    try:
        pname = str(plan_name or "").strip().lower()
        if pname in ("standard", "pro"):
            parsed["description"] = _augment_spec_tables_for_standard_pro(
                db=db,
                shop=shop,
                target_locale=target_locale,
                description_html=str(parsed.get("description") or ""),
                source_text=processed_description,
                auto_convert_units=bool(auto_convert_units),
            )
    except Exception as e:
        logger.warning("[SpecTables] skipped shop=%s locale=%s err=%s", shop, target_locale, e)
    # All plans: cheap SEO recommendations during Optimize (non-blocking).
    try:
        seo_recs = _generate_seo_recommendations(
            db=db,
            shop=shop,
            target_locale=target_locale,
            product_name=product_name,
            category=category,
            description_html=str(parsed.get("description") or ""),
            seo_title=str(parsed.get("seo_title") or ""),
            seo_description=str(parsed.get("seo_description") or ""),
        )
        if seo_recs:
            parsed["seo_recommendations"] = seo_recs
    except Exception as e:
        logger.warning("[SEORecs] skipped shop=%s locale=%s err=%s", shop, target_locale, e)
    # Enforce SEO length constraints deterministically (post-process).
    parsed["seo_title"] = _clamp_len(str(parsed.get("seo_title") or ""), 70)
    parsed["seo_description"] = _clamp_len(str(parsed.get("seo_description") or ""), 160)

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
        "data": {
            **parsed,
            "competitor_titles": competitor_titles,
            "competitor_results": competitor_results,
        },
        "discovered_values": discovered_values,
    }

async def process_generation_request(
    db: Session,
    request: RewriteRequest,
    user: User,
    plan,
):
    shop = user.username
    if not limiter.is_allowed(shop):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")
    
    if request.stream and not plan.can_stream_responses:
        raise HTTPException(status_code=403, detail="Streaming not supported on your current plan.")

    target_locale = request.target_locale or "en"
    plan_name = str(getattr(plan, "name", "") or "")
    tone_profile = _effective_tone(plan_name, getattr(request, "tone_profile", None))
    dynamic_prompt = _build_dynamic_prompt(
        target_locale,
        auto_convert_units=bool(getattr(request, "auto_convert_units", False)),
        tone_profile=tone_profile,
        plan_name=plan_name,
        brand_name=str(shop or "").replace(".myshopify.com", ""),
    )

    try:
        if request.stream:
            logger.info(f"🌊 Initiating Streaming Response for: {shop}")
            return openai_service.create_streaming_response(
                product_name=request.product_name,
                category=request.category,
                japanese_description=request.japanese_description,
                db=db,
                shop_domain=shop,
                system_prompt=dynamic_prompt
            )

        # Standard non-streaming flow
        processed_desc = detect_and_label_sections(request.japanese_description)
        access_token = get_shop_access_token(db, shop) if request.product_id else None
        
        if request.product_id and not access_token:
            logger.error(f"❌ Access Token missing for shop {shop} during product update.")
            raise HTTPException(status_code=500, detail="Shopify Access Token not found. Re-install app.")

        primary_locale = "en"
        competitor_context: list[dict] | None = None
        plan_name = str(getattr(plan, "name", "") or "")

        if plan_name in ("Standard", "Pro"):
            keyword = f"{request.product_name or ''} {request.category or ''}".strip()
            tasks = [
                serp_service.fetch_top_results(keyword),
                _fetch_primary_locale(shop, access_token),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            serp_res, primary_res = results[0], results[1]
            if not isinstance(serp_res, Exception) and serp_res:
                competitor_context = serp_res
            if not isinstance(primary_res, Exception) and primary_res:
                primary_locale = primary_res
        else:
            primary_locale = await _fetch_primary_locale(shop, access_token)

        result = await _generate_and_save_for_locale(
            db,
            shop,
            request.product_id,
            request.product_name,
            request.category,
            processed_desc,
            target_locale,
            primary_locale,
            access_token,
            auto_convert_units=bool(getattr(request, "auto_convert_units", False)),
            tone_profile=tone_profile,
            plan_name=plan_name,
            competitor_context=competitor_context,
            remove_irrelevant_content=bool(getattr(request, "remove_irrelevant_content", True)),
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
):
    """
    Core logic for bulk generation requests.
    Checks plan, rate limits, and parallelizes generation for multiple locales.
    """
    shop = user.username
    if not limiter.is_allowed(shop):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")

    # 1. Plan Check for Bulk (Multi-locale)
    if len(request.target_locales) > 1 and plan.name not in ("Standard", "Pro"):
        raise HTTPException(
            status_code=403,
            detail="Bulk multi-market generation requires Standard or Pro plan.",
        )

    try:
        logger.debug(
            "[BulkCore] start shop=%s plan=%s product_id=%s target_locales=%s desc_len=%s",
            shop,
            getattr(plan, "name", None),
            getattr(request, "product_id", None),
            list(getattr(request, "target_locales", []) or []),
            len(getattr(request, "japanese_description", "") or ""),
        )
        access_token = get_shop_access_token(db, shop) if request.product_id else None
        if request.product_id and not access_token:
            raise HTTPException(status_code=500, detail="Shopify Access Token not found.")

        # 2. Fetch Primary Locale + SERP context in parallel for Standard/Pro
        primary_locale = "en"
        competitor_context: list[dict] | None = None
        plan_name = str(getattr(plan, "name", "") or "")

        if plan_name in ("Standard", "Pro"):
            keyword = f"{request.product_name or ''} {request.category or ''}".strip()
            tasks = [
                serp_service.fetch_top_results(keyword),
                _fetch_primary_locale(shop, access_token),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            serp_res, primary_res = results[0], results[1]
            if not isinstance(serp_res, Exception) and serp_res:
                competitor_context = serp_res
            if not isinstance(primary_res, Exception) and primary_res:
                primary_locale = primary_res
        else:
            primary_locale = await _fetch_primary_locale(shop, access_token)

        processed_desc = detect_and_label_sections(request.japanese_description)

        # 3. Save ordering to avoid translation digest invalidation:
        # If the primary locale is included, update it LAST. Otherwise translationsRegister for
        # secondary locales can fail with "Translatable content hash is invalid" if primary content
        # changes during the digest->register window.
        target_locales = list(request.target_locales or [])
        non_primary_locales = [l for l in target_locales if l != primary_locale]
        primary_locales = [l for l in target_locales if l == primary_locale]

        tone_profile = _effective_tone(plan_name, getattr(request, "tone_profile", None))

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
                auto_convert_units=bool(getattr(request, "auto_convert_units", False)),
                tone_profile=tone_profile,
                plan_name=plan_name,
                competitor_context=competitor_context,
                remove_irrelevant_content=bool(getattr(request, "remove_irrelevant_content", True)),
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
                logger.exception("[BulkCore] item_failed shop=%s err=%s", shop, res)
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
        logger.debug(
            "[BulkCore] done shop=%s success=%s failed=%s primary_locale=%s",
            shop,
            len(success_locales),
            len(failed_locales),
            primary_locale,
        )
        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Error in bulk processing for {shop}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

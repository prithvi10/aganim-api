import re
from datetime import datetime, timezone
from html import unescape
from typing import Iterable
import json

import httpx
from sqlalchemy.orm import Session

from src.main.config.prompts import (
    BRAND_CONTEXT_CLEAN_PROMPT,
    BRAND_CONTEXT_SUMMARY_PROMPT_TEMPLATE,
)
from src.main.db.db_models import StoreContext, Shop
from src.main.logging.logger import get_logger
from src.main.rag.chunking import chunk_text
from src.main.rag.embedding import embed_texts
from src.main.service.open_ai_api_service import OpenAIService
from src.main.utils.llm_parser import parse_llm_json

logger = get_logger(__name__)


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def scrape_urls(urls: Iterable[str]) -> list[dict]:
    results: list[dict] = []
    client = httpx.Client(timeout=12.0, follow_redirects=True)
    for url in urls:
        u = str(url or "").strip()
        if not u:
            continue
        try:
            resp = client.get(u)
            resp.raise_for_status()
            text = _html_to_text(resp.text or "")
            if text:
                results.append({"source_url": u, "source_type": "web", "text": text})
        except Exception as e:
            logger.warning("[BrandIngest] scrape_failed url=%s err=%s", u, e)
    return results


def extract_file_text(*, file_b64: str, mime_type: str) -> str:
    if not file_b64 or not mime_type:
        return ""
    service = OpenAIService()
    raw = service.extract_text_from_file(file_b64=file_b64, mime_type=mime_type)
    parsed = parse_llm_json(raw or "")
    if isinstance(parsed, dict) and parsed.get("text"):
        return str(parsed.get("text") or "").strip()
    return str(raw or "").strip()


def _clean_brand_text(raw_text: str) -> dict:
    service = OpenAIService()
    payload = {"raw_text": raw_text}
    raw = service.generate_json(
        system_prompt=BRAND_CONTEXT_CLEAN_PROMPT,
        user_json=payload,
        temperature=0.2,
        max_tokens=800,
    )
    parsed = parse_llm_json(raw or "")
    if not isinstance(parsed, dict):
        return {"clean_text": raw_text.strip(), "pillars": []}
    clean_text = str(parsed.get("clean_text") or "").strip()
    pillars = parsed.get("pillars") if isinstance(parsed.get("pillars"), list) else []
    return {
        "clean_text": clean_text or raw_text.strip(),
        "pillars": [str(p).strip() for p in pillars if str(p).strip()],
    }


def _summarize_brand_context(chunks: list[str], *, language: str) -> dict:
    if not chunks:
        return {"summary": "", "key_facts": []}
    service = OpenAIService()
    payload = {"brand_context": "\n\n".join(chunks[:12])}
    raw = service.generate_json(
        system_prompt=BRAND_CONTEXT_SUMMARY_PROMPT_TEMPLATE.format(language=language),
        user_json=payload,
        temperature=0.2,
        max_tokens=500,
    )
    parsed = parse_llm_json(raw or "")
    if isinstance(parsed, dict):
        summary = str(parsed.get("summary") or "").strip()
        key_facts_raw = parsed.get("key_facts")
        key_facts: list[str] = []
        if isinstance(key_facts_raw, list):
            key_facts = [str(k).strip() for k in key_facts_raw if str(k).strip()]
        return {"summary": summary, "key_facts": key_facts}
    return {"summary": str(raw or "").strip(), "key_facts": []}


def ingest_brand_context(
    db: Session,
    *,
    shop_id: str,
    raw_texts: list[dict],
    max_len: int = 500,
    overlap: int = 50,
) -> dict:
    """
    Ingest brand context into store_context.
    raw_texts: list of dicts {text, source_url, source_type}
    """
    if not shop_id:
        raise ValueError("shop_id required")

    cleaned_items: list[dict] = []
    for item in raw_texts:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        cleaned = _clean_brand_text(text)
        cleaned_items.append(
            {
                "source_url": str(item.get("source_url") or "").strip() or None,
                "source_type": str(item.get("source_type") or "text").strip(),
                "clean_text": cleaned.get("clean_text") or "",
                "pillars": cleaned.get("pillars") or [],
            }
        )

    chunks = []
    chunk_meta = []
    for item in cleaned_items:
        for chunk in chunk_text(item["clean_text"], max_len=max_len, overlap=overlap):
            if not chunk.content.strip():
                continue
            chunks.append(chunk.content)
            chunk_meta.append(
                {
                    "source_url": item.get("source_url"),
                    "source_type": item.get("source_type"),
                    "chunk_index": chunk.chunk_index,
                    "pillars": item.get("pillars") or [],
                }
            )

    if not chunks:
        return {"inserted": 0, "summary": "", "chunk_count": 0}

    vectors = embed_texts(chunks)
    now = datetime.now(timezone.utc)
    inserted = 0

    # Best-effort cleanup for same source URLs (avoid duplicates).
    try:
        source_urls = {item.get("source_url") for item in cleaned_items if item.get("source_url")}
        if source_urls and db.bind and db.bind.dialect.name == "postgresql":
            for url in source_urls:
                db.query(StoreContext).filter(
                    StoreContext.shop_id == shop_id,
                    StoreContext.metadata_json["source_url"].astext == str(url),
                ).delete(synchronize_session=False)
    except Exception as e:
        logger.warning("[BrandIngest] dedupe_failed shop=%s err=%s", shop_id, e)

    for content, meta, vec in zip(chunks, chunk_meta, vectors):
        row = StoreContext(
            shop_id=shop_id,
            content=content,
            embedding=vec,
            metadata_json={
                "source_url": meta.get("source_url"),
                "source_type": meta.get("source_type"),
                "chunk_index": meta.get("chunk_index"),
                "pillars": meta.get("pillars"),
                "extracted_at": now.isoformat(),
            },
        )
        db.add(row)
        inserted += 1

    summary_en_payload = _summarize_brand_context(chunks, language="English")
    summary_ja_payload = _summarize_brand_context(chunks, language="Japanese")
    summary_en = str(summary_en_payload.get("summary") or "").strip()
    summary_ja = str(summary_ja_payload.get("summary") or "").strip()
    key_facts_en = summary_en_payload.get("key_facts") or []
    key_facts_ja = summary_ja_payload.get("key_facts") or []
    key_facts = key_facts_en or key_facts_ja or []
    brand_context = {
        "summary_en": summary_en,
        "summary_ja": summary_ja,
        "key_facts_en": key_facts_en,
        "key_facts_ja": key_facts_ja,
    }
    try:
        shop = db.query(Shop).filter(Shop.domain == shop_id).first()
        if shop:
            # Store JSON blob for UI use.
            shop.brand_context = brand_context
            shop.brand_context_updated_at = now
            shop.brand_context_status = "ready"
            shop.brand_context_last_error = None
            db.add(shop)
    except Exception as e:
        logger.warning("[BrandIngest] summary_save_failed shop=%s err=%s", shop_id, e)

    db.commit()
    return {
        "inserted": inserted,
        "summary_en": summary_en,
        "summary_ja": summary_ja,
        "summary": summary_en or summary_ja,
        "key_facts": key_facts,
        "key_facts_en": key_facts_en,
        "key_facts_ja": key_facts_ja,
        "brand_context": brand_context,
        "chunk_count": len(chunks),
    }

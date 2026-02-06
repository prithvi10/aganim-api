"""
BrandIngestService - Brand context ingestion.

Moved from service/brand_context_ingest.py to consolidate services.
"""

import re
from datetime import datetime, timezone
from html import unescape
from typing import Iterable
import json

import httpx
from sqlalchemy.orm import Session

from src.main.config.prompts import BRAND_CONTEXT_CLEAN_PROMPT
from src.main.db.db_models import StoreContext, Shop
from src.main.logging.logger import get_logger
from src.main.rag.chunking import chunk_text
from src.main.rag.embedding import embed_texts
from src.main.utils.llm_parser import parse_llm_json

logger = get_logger(__name__)


def _get_openai_service():
    """Lazy import to avoid circular dependency."""
    from src.main.services.openai_legacy_service import OpenAIService
    return OpenAIService()


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
    service = _get_openai_service()
    raw = service.extract_text_from_file(file_b64=file_b64, mime_type=mime_type)
    parsed = parse_llm_json(raw or "")
    if isinstance(parsed, dict) and parsed.get("text"):
        return str(parsed.get("text") or "").strip()
    return str(raw or "").strip()


def _clean_brand_text(raw_text: str) -> dict:
    service = _get_openai_service()
    payload = {"raw_text": raw_text}
    raw = service.generate_json(
        system_prompt=BRAND_CONTEXT_CLEAN_PROMPT,
        user_json=payload,
        temperature=0.2,
        max_tokens=1500,
    )
    parsed = parse_llm_json(raw or "")
    if not isinstance(parsed, dict):
        return {
            "en": {"clean_text": raw_text.strip(), "pillars": []},
            "ja": {"clean_text": "", "pillars": []}
        }
    
    # Ensure nested keys exist
    en = parsed.get("en") or {}
    ja = parsed.get("ja") or {}
    
    return {
        "en": {
            "clean_text": str(en.get("clean_text") or "").strip(),
            "pillars": [str(p).strip() for p in (en.get("pillars") or []) if str(p).strip()]
        },
        "ja": {
            "clean_text": str(ja.get("clean_text") or "").strip(),
            "pillars": [str(p).strip() for p in (ja.get("pillars") or []) if str(p).strip()]
        }
    }



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
                "clean_blob": cleaned, # Store the full nested EN/JP structure
            }
        )

    # Process clean_text results to chunks
    chunks = []
    chunk_meta = []
    
    # We will prioritize English for chunking if available, or fallback to Japanese.
    # The chunking logic remains the same (StoreContext stores vectors).
    # NOTE: StoreContext 'content' is used for RAG retrieval. If we want cross-lingual RAG,
    # we typically embed the language that matches the user's queries.
    # Here we default to storing the English clean text if present, else Japanese.
    
    for item in cleaned_items:
        # Extract clean text from nested structure
        # item['clean_blob'] = { 'en': {...}, 'ja': {...} }
        blob = item.get("clean_blob") or {}
        en_text = blob.get("en", {}).get("clean_text") or ""
        ja_text = blob.get("ja", {}).get("clean_text") or ""
        
        # Determine what to vector-store. 
        # Strategy: Store both if available? Or just English?
        # Current logic iterates 'cleaned_items' and makes chunks. 
        # Let's store both segments as separate chunks to allow multilingual retrieval match.
        
        texts_to_chunk = []
        if en_text:
            texts_to_chunk.append({"text": en_text, "lang": "en", "pillars": blob.get("en", {}).get("pillars") or []})
        if ja_text and ja_text != en_text:
            texts_to_chunk.append({"text": ja_text, "lang": "ja", "pillars": blob.get("ja", {}).get("pillars") or []})
            
        # If both empty, fallback to raw? But _clean_brand_text guarantees structure.
        if not texts_to_chunk:
             continue

        for txt_obj in texts_to_chunk:
            for chunk in chunk_text(txt_obj["text"], max_len=max_len, overlap=overlap):
                if not chunk.content.strip():
                    continue
                chunks.append(chunk.content)
                chunk_meta.append(
                    {
                        "source_url": item.get("source_url"),
                        "source_type": item.get("source_type"),
                        "chunk_index": chunk.chunk_index,
                        "pillars": txt_obj["pillars"],
                        "lang": txt_obj["lang"]
                    }
                )

    if not chunks:
        return {"inserted": 0, "chunk_count": 0}

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
                "lang": meta.get("lang"),
                "extracted_at": now.isoformat(),
            },
        )
        db.add(row)
        inserted += 1

    # Consolidated brand_context blob construction
    # Merge pillars from all items
    pillars_en = set()
    pillars_ja = set()
    clean_text_en_parts = []
    clean_text_ja_parts = []

    for item in cleaned_items:
        blob = item.get("clean_blob") or {}
        
        pe = blob.get("en", {}).get("pillars") or []
        pj = blob.get("ja", {}).get("pillars") or []
        pillars_en.update(pe)
        pillars_ja.update(pj)
        
        te = blob.get("en", {}).get("clean_text") or ""
        tj = blob.get("ja", {}).get("clean_text") or ""
        if te: clean_text_en_parts.append(te)
        if tj: clean_text_ja_parts.append(tj)

    brand_context = {
        "en": {
            "clean_text": "\n\n".join(clean_text_en_parts),
            "pillars": list(pillars_en)
        },
        "ja": {
            "clean_text": "\n\n".join(clean_text_ja_parts),
            "pillars": list(pillars_ja)
        }
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
        "brand_context": brand_context,
        "chunk_count": len(chunks),
    }

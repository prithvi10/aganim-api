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

from src.shared.config.prompts import BRAND_CONTEXT_CLEAN_PROMPT
from src.ecommerce.db.models import StoreContext, Shop, BrandEntity
from sqlalchemy.orm.attributes import flag_modified

from src.shared.logging.logger import get_logger
from src.agentic_core.rag.chunking import chunk_text
from src.agentic_core.rag.embedding import embed_texts
from src.shared.utils.llm_parser import parse_llm_json
from typing import Optional, List

logger = get_logger(__name__)


def _get_openai_service():
    """Lazy import to avoid circular dependency."""
    from src.ecommerce.services.openai_legacy_service import OpenAIService
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
    set_status: bool = True,
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
            if set_status:
                # Only set "ready" when called standalone.
                # When called from ingest_brand_context_with_intelligence(),
                # the caller / background task manages the status to avoid
                # a race where status becomes "ready" before intelligence extraction.
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


async def ingest_brand_context_with_intelligence(
    db: Session,
    *,
    shop_id: str,
    raw_texts: list[dict],
    extract_intelligence: bool = True,
    max_len: int = 500,
    overlap: int = 50,
    llm_service=None,
) -> dict:
    """
    Enhanced brand ingestion with strategic intelligence extraction.
    
    Extends the base ingest_brand_context function with:
    1. Entity extraction per chunk
    2. Strategic intelligence extraction
    3. Triplet building for knowledge graph
    4. Entity metadata tagging on chunks
    
    Args:
        db: SQLAlchemy database session
        shop_id: Shop domain identifier
        raw_texts: List of dicts with {text, source_url, source_type}
        extract_intelligence: Whether to extract strategic intelligence (default: True)
        max_len: Maximum chunk length
        overlap: Chunk overlap size
        llm_service: Optional LLMService instance (will create if not provided)
    
    Returns:
        Dict with inserted count, brand_context, strategic_intelligence, triplet_count, entity_count
    """
    if not shop_id:
        raise ValueError("shop_id required")
    
    # Step 1: Run base ingestion to get cleaned text and chunks
    # set_status=False: don't let base ingest set "ready" prematurely —
    # the background task wrapper sets "ready" only after intelligence extraction finishes.
    base_result = ingest_brand_context(
        db=db,
        shop_id=shop_id,
        raw_texts=raw_texts,
        max_len=max_len,
        overlap=overlap,
        set_status=False,
    )
    
    if not extract_intelligence:
        return base_result
    
    # Step 2: Extract strategic intelligence and entities
    try:
        # Get LLM service if not provided
        if llm_service is None:
            from src.agentic_core.llm.llm_service import LLMService
            llm_service = LLMService()
        
        from src.ecommerce.services.intelligence_extractor import (
            IntelligenceExtractorService,
            Entity,
        )
        extractor = IntelligenceExtractorService(llm_service)
        
        # Get full brand text for strategic intelligence extraction
        brand_context = base_result.get("brand_context", {})
        full_text = brand_context.get("en", {}).get("clean_text", "")
        existing_pillars = brand_context.get("en", {}).get("pillars", [])
        
        # Extract strategic intelligence
        strategic_intel = None
        if full_text:
            try:
                strategic_intel = await extractor.extract_strategic_audit(
                    brand_text=full_text,
                    existing_pillars=existing_pillars if existing_pillars else None,
                )
            except Exception as e:
                logger.warning(
                    "[BrandIngest] Strategic intelligence extraction failed shop=%s err=%s",
                    shop_id,
                    e,
                )
        
        # Step 3: Extract entities from chunks and build triplets
        all_entities: List[Entity] = []
        chunk_id_to_entities = {}
        
        # Get all chunks we just inserted
        chunks = (
            db.query(StoreContext)
            .filter(StoreContext.shop_id == shop_id)
            .order_by(StoreContext.created_at.desc())
            .limit(base_result.get("chunk_count", 0))
            .all()
        )
        
        # Extract entities from each chunk
        for chunk_row in chunks:
            try:
                entities = await extractor.extract_entities_from_chunk(chunk_row.content)
                all_entities.extend(entities)
                chunk_id_to_entities[chunk_row.id] = entities
                
                # Update chunk metadata with entities.
                # Create a NEW dict so SQLAlchemy detects the JSONB mutation.
                metadata = dict(chunk_row.metadata_json or {})
                entity_tags = [f"{e.type.value}:{e.entity}" for e in entities]
                metadata["entities"] = entity_tags
                chunk_row.metadata_json = metadata
                flag_modified(chunk_row, "metadata_json")
                db.add(chunk_row)
            except Exception as e:
                logger.warning(
                    "[BrandIngest] Entity extraction failed chunk_id=%s err=%s",
                    chunk_row.id,
                    e,
                )
        
        # Step 4: Build triplets from entities
        triplets = []
        if all_entities and full_text:
            try:
                triplets = await extractor.build_triplets(
                    entities=all_entities[:50],  # Limit to top 50 for triplet building
                    source_text=full_text[:3000],  # Limit context size
                )
                
                # Store triplets in brand_entities table
                for triplet in triplets:
                    entity_row = BrandEntity(
                        shop_id=shop_id,
                        subject=triplet.subject,
                        subject_type=triplet.subject_type.value,
                        relation=triplet.relation,
                        object=triplet.object,
                        object_type=triplet.object_type.value,
                        confidence=triplet.confidence,
                        source_chunk_id=triplet.source_chunk_id,
                    )
                    db.add(entity_row)
            except Exception as e:
                logger.warning(
                    "[BrandIngest] Triplet building failed shop=%s err=%s",
                    shop_id,
                    e,
                )
        
        # Step 5: Store strategic intelligence on Shop
        if strategic_intel:
            try:
                shop = db.query(Shop).filter(Shop.domain == shop_id).first()
                if shop:
                    shop.strategic_intelligence = strategic_intel.model_dump()
                    shop.strategic_intelligence_updated_at = datetime.now(timezone.utc)
                    db.add(shop)
            except Exception as e:
                logger.warning(
                    "[BrandIngest] Strategic intelligence save failed shop=%s err=%s",
                    shop_id,
                    e,
                )
        
        db.commit()
        
        return {
            "inserted": base_result.get("inserted", 0),
            "brand_context": brand_context,
            "chunk_count": base_result.get("chunk_count", 0),
            "strategic_intelligence": strategic_intel.model_dump() if strategic_intel else None,
            "triplet_count": len(triplets),
            "entity_count": len(all_entities),
        }
    
    except Exception as e:
        logger.error(
            "[BrandIngest] Intelligence extraction pipeline failed shop=%s err=%s",
            shop_id,
            e,
        )
        # Return base result even if intelligence extraction fails
        return base_result

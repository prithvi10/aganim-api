"""
RAGService - Generic Retrieval Augmented Generation service.

Handles:
- Vector similarity search on ``ContextChunk`` (generic agentic_core model)
- Entity-based chunk expansion via JSONB metadata on ``ContextChunk``
- Delegation of domain-specific operations (brand summary, knowledge graph,
  strategic intelligence) to an optional ``RAGStorageAdapter``.
"""

from time import perf_counter
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import or_

from src.shared.logging.logger import get_logger
from src.agentic_core.rag.embedding import embed_texts  # noqa: F401 - used in _vector_search

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from src.agentic_core.interfaces import RAGStorageAdapter

logger = get_logger(__name__)


def _get_context_chunk_model():
    """Lazy import to avoid circular dependencies at module level."""
    from src.agentic_core.db.models import ContextChunk
    return ContextChunk


class RAGService:
    """
    Generic RAG service for context retrieval.

    Core vector search operates on :class:`ContextChunk` which lives inside
    the ``agentic_core`` boundary.  Domain-specific lookups (brand summary,
    knowledge-graph traversal, strategic intelligence) are delegated to an
    optional :class:`RAGStorageAdapter`.

    Used by:
        - Any agent needing context retrieval
        - BaseAgent.perceive() for strategic intelligence
    """

    def __init__(self, storage_adapter: Optional["RAGStorageAdapter"] = None):
        self._adapter = storage_adapter

    # ------------------------------------------------------------------
    # Core vector search (generic - ContextChunk only)
    # ------------------------------------------------------------------

    async def get_brand_context(
        self,
        db: "Session",
        shop_id: str,
        product_text: str,
        limit: int = 3,
    ) -> List[Dict]:
        """
        Retrieve relevant context chunks via vector similarity search.

        Args:
            db: SQLAlchemy database session
            shop_id: Tenant identifier
            product_text: Query text for embedding similarity
            limit: Maximum number of context chunks to return

        Returns:
            List of dicts with ``content`` and ``metadata`` keys
        """
        if not shop_id or not product_text:
            return []

        try:
            chunks = _vector_search(
                db, shop_id=shop_id, product_text=product_text, limit=limit,
            )
            return chunks
        except Exception as e:
            logger.warning(
                "[RAGService] Failed to get brand context shop=%s err=%s",
                shop_id, e,
            )
            return []

    # Alias for backward-compat
    get_context_chunks = get_brand_context

    # ------------------------------------------------------------------
    # Entity-based chunk expansion (generic - ContextChunk JSONB)
    # ------------------------------------------------------------------

    async def _get_chunks_by_entities(
        self,
        db: "Session",
        shop_id: str,
        entities: List[str],
        exclude_ids: Optional[List[int]] = None,
        limit: int = 3,
    ) -> List[Dict]:
        """Find chunks whose ``metadata_json.entities`` overlap *entities*."""
        if not entities:
            return []

        ContextChunk = _get_context_chunk_model()

        try:
            query = db.query(ContextChunk).filter(
                ContextChunk.tenant_id == shop_id,
            )

            if exclude_ids:
                query = query.filter(~ContextChunk.id.in_(exclude_ids))

            entity_conditions = []
            for entity in entities[:5]:
                entity_key = entity.split(":", 1)[-1] if ":" in entity else entity
                entity_conditions.append(
                    ContextChunk.metadata_json["entities"].astext.contains(entity_key)
                )

            if entity_conditions:
                query = query.filter(or_(*entity_conditions))

            rows = query.limit(limit).all()

            return [
                {
                    "content": r.content,
                    "metadata": r.metadata_json or {},
                    "id": r.id,
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(
                "[RAGService] Entity-based chunk retrieval failed shop=%s err=%s",
                shop_id, e,
            )
            return []

    # ------------------------------------------------------------------
    # Similar-product search (generic convenience)
    # ------------------------------------------------------------------

    async def search_similar_products(
        self,
        db: "Session",
        shop_id: str,
        query_text: str,
        limit: int = 5,
    ) -> List[Dict]:
        """Search for similar context chunks by embedding similarity."""
        return await self.get_brand_context(
            db=db, shop_id=shop_id, product_text=query_text, limit=limit,
        )

    # ------------------------------------------------------------------
    # Adapter-delegated methods
    # ------------------------------------------------------------------

    async def get_brand_summary(
        self,
        db: "Session",
        shop_id: str,
    ) -> Optional[Dict]:
        """Return tenant/brand summary.  Delegates to adapter if present."""
        if self._adapter is None:
            return None
        try:
            return await self._adapter.get_tenant_summary(db, shop_id)
        except Exception as e:
            logger.warning(
                "[RAGService] get_brand_summary failed shop=%s err=%s",
                shop_id, e,
            )
            return None

    async def get_strategic_intelligence(
        self,
        db: "Session",
        shop_id: str,
    ) -> Optional[Dict]:
        """Return strategic intelligence JSON.  Delegates to adapter."""
        if self._adapter is None:
            return None
        try:
            return await self._adapter.get_strategic_intelligence(db, shop_id)
        except Exception as e:
            logger.warning(
                "[RAGService] get_strategic_intelligence failed shop=%s err=%s",
                shop_id, e,
            )
            return None

    # Keep underscore alias so old callers still work
    _get_strategic_intelligence = get_strategic_intelligence

    async def _traverse_knowledge_graph(
        self,
        db: "Session",
        shop_id: str,
        seed_entities: List[str],
        depth: int = 2,
    ) -> List[Dict]:
        """Traverse knowledge graph.  Delegates to adapter."""
        if self._adapter is None:
            return []
        try:
            return await self._adapter.traverse_knowledge_graph(
                db, shop_id, seed_entities, depth,
            )
        except Exception as e:
            logger.warning(
                "[RAGService] traverse_knowledge_graph failed shop=%s err=%s",
                shop_id, e,
            )
            return []

    # ------------------------------------------------------------------
    # Composite: complete context (vector + entities + graph + intel)
    # ------------------------------------------------------------------

    async def get_complete_context(
        self,
        db: "Session",
        shop_id: str,
        product_text: str,
        limit: int = 5,
    ) -> Dict:
        """
        Get complete context combining vector search, entity expansion,
        knowledge-graph traversal, and strategic intelligence.
        """
        base_chunks = await self.get_brand_context(
            db=db, shop_id=shop_id, product_text=product_text, limit=limit,
        )

        # Extract entities from base chunks
        product_entities: List[str] = []
        for chunk in base_chunks:
            entities = chunk.get("metadata", {}).get("entities", [])
            if isinstance(entities, list):
                product_entities.extend(entities)
        product_entities = list(set(product_entities))[:10]

        # Entity-based expansion
        expanded_chunks: List[Dict] = []
        if product_entities:
            expanded_chunks = await self._get_chunks_by_entities(
                db=db, shop_id=shop_id, entities=product_entities, limit=3,
            )

        # Knowledge-graph traversal (adapter)
        related_triplets: List[Dict] = []
        if product_entities:
            entity_names = [
                e.split(":", 1)[-1] if ":" in e else e
                for e in product_entities
            ]
            related_triplets = await self._traverse_knowledge_graph(
                db=db, shop_id=shop_id, seed_entities=entity_names, depth=2,
            )

        # Strategic intelligence (adapter)
        strategic_intel = await self.get_strategic_intelligence(db, shop_id)

        return {
            "chunks": base_chunks,
            "expanded_chunks": expanded_chunks,
            "related_triplets": related_triplets,
            "strategic_rules": strategic_intel,
        }


# --------------------------------------------------------------------------
# Module-level helper (standalone function kept for backward compat)
# --------------------------------------------------------------------------

def get_brand_context(
    db: "Session",
    *,
    shop_id: str,
    product_text: str,
    limit: int = 3,
) -> list[dict]:
    """Standalone vector similarity search on ContextChunk."""
    return _vector_search(db, shop_id=shop_id, product_text=product_text, limit=limit)


def _vector_search(
    db: "Session",
    *,
    shop_id: str,
    product_text: str,
    limit: int = 3,
) -> list[dict]:
    """Low-level vector search using ContextChunk + embedding."""
    if not shop_id or not product_text:
        return []

    start = perf_counter()

    vectors = embed_texts([product_text])
    if not vectors:
        return []
    query_vec = vectors[0]

    ContextChunk = _get_context_chunk_model()

    try:
        rows = (
            db.query(ContextChunk)
            .filter(ContextChunk.tenant_id == shop_id)
            .order_by(ContextChunk.embedding.cosine_distance(query_vec))
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.warning("[BrandContext] query_failed shop=%s err=%s", shop_id, e)
        return []

    out = []
    for row in rows:
        out.append({
            "content": row.content,
            "metadata": row.metadata_json or {},
        })

    dur_ms = (perf_counter() - start) * 1000.0
    logger.info(
        "[BrandContext] retrieved shop=%s count=%s dur_ms=%.1f",
        shop_id, len(out), dur_ms,
    )
    return out

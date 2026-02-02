"""
RAGService - Retrieval Augmented Generation service for brand context.

Consolidates brand context retrieval logic into a clean service interface.
Previously split between service/brand_context_retrieval.py and this file.
"""

from time import perf_counter
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from src.main.db.db_models import StoreContext, Shop
from src.main.logging.logger import get_logger
from src.main.rag.embedding import embed_texts

logger = get_logger(__name__)


def get_brand_context(
    db: Session,
    *,
    shop_id: str,
    product_text: str,
    limit: int = 3,
) -> list[dict]:
    """
    Retrieve brand context chunks via vector similarity search.
    
    This is the core RAG retrieval function, now consolidated into services.
    Previously in service/brand_context_retrieval.py.
    """
    if not shop_id or not product_text:
        return []

    start = perf_counter()
    vectors = embed_texts([product_text])
    if not vectors:
        return []
    query_vec = vectors[0]

    try:
        rows = (
            db.query(StoreContext)
            .filter(StoreContext.shop_id == shop_id)
            .order_by(StoreContext.embedding.cosine_distance(query_vec))
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.warning("[BrandContext] query_failed shop=%s err=%s", shop_id, e)
        return []

    out = []
    for row in rows:
        out.append(
            {
                "content": row.content,
                "metadata": row.metadata_json or {},
            }
        )

    dur_ms = (perf_counter() - start) * 1000.0
    logger.info(
        "[BrandContext] retrieved shop=%s count=%s dur_ms=%.1f",
        shop_id,
        len(out),
        dur_ms,
    )
    return out


class RAGService:
    """
    Service for retrieving brand context via RAG (Retrieval Augmented Generation).
    
    Uses vector embeddings to find relevant brand context chunks for a product.
    
    Used by:
        - CopywriterAgent for brand-aware content generation
        - Any agent needing brand context
    """

    def __init__(self):
        """Initialize RAGService."""
        pass  # No configuration needed; uses existing infrastructure

    async def get_brand_context(
        self,
        db: Session,
        shop_id: str,
        product_text: str,
        limit: int = 3,
    ) -> List[Dict]:
        """
        Retrieve relevant brand context chunks for a product.
        
        Uses embedding similarity search to find the most relevant brand
        context chunks stored for this shop.
        
        Args:
            db: SQLAlchemy database session
            shop_id: Shop domain identifier
            product_text: Product text to match against (title + description)
            limit: Maximum number of context chunks to return
        
        Returns:
            List of dicts with 'content' and 'metadata' keys
        """
        if not shop_id or not product_text:
            return []

        try:
            # Use the consolidated function
            chunks = get_brand_context(
                db,
                shop_id=shop_id,
                product_text=product_text,
                limit=limit,
            )
            return chunks
        except Exception as e:
            logger.warning(
                "[RAGService] Failed to get brand context shop=%s err=%s",
                shop_id,
                e,
            )
            return []

    async def get_brand_summary(
        self,
        db: Session,
        shop_id: str,
    ) -> Optional[Dict]:
        """
        Get the brand summary for a shop.
        
        Returns the processed brand context blob stored on the Shop record.
        
        Args:
            db: SQLAlchemy database session
            shop_id: Shop domain identifier
        
        Returns:
            Brand context dict or None if not found
        """
        try:
            shop = db.query(Shop).filter(Shop.domain == shop_id).first()
            if not shop:
                return None

            brand_context = getattr(shop, "brand_context", None)
            if not brand_context:
                return None

            # Handle both string and dict formats
            if isinstance(brand_context, str):
                import json
                try:
                    return json.loads(brand_context)
                except Exception:
                    return None
            
            return brand_context if isinstance(brand_context, dict) else None

        except Exception as e:
            logger.warning(
                "[RAGService] Failed to get brand summary shop=%s err=%s",
                shop_id,
                e,
            )
            return None

    async def search_similar_products(
        self,
        db: Session,
        shop_id: str,
        query_text: str,
        limit: int = 5,
    ) -> List[Dict]:
        """
        Search for similar product contexts in the brand knowledge base.
        
        Useful for finding related products or past successful descriptions.
        
        Args:
            db: SQLAlchemy database session
            shop_id: Shop domain identifier
            query_text: Text to search for
            limit: Maximum results to return
        
        Returns:
            List of similar context chunks
        """
        # For now, delegate to get_brand_context
        # Future: Could use a different embedding index for products
        return await self.get_brand_context(
            db=db,
            shop_id=shop_id,
            product_text=query_text,
            limit=limit,
        )

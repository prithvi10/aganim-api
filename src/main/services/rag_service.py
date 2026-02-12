"""
RAGService - Retrieval Augmented Generation service for brand context.

Consolidates brand context retrieval logic into a clean service interface.
Previously split between service/brand_context_retrieval.py and this file.
"""

from time import perf_counter
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from src.main.db.db_models import StoreContext, Shop, BrandEntity
from src.main.logging.logger import get_logger
from src.main.rag.embedding import embed_texts
from sqlalchemy import or_

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
    
    async def get_complete_context(
        self,
        db: Session,
        shop_id: str,
        product_text: str,
        limit: int = 5,
    ) -> Dict:
        """
        Get complete brand context with entity expansion.
        
        Combines:
        1. Vector similarity search (standard RAG)
        2. Entity-based expansion (chunks sharing entities)
        3. Knowledge graph traversal (related triplets)
        4. Strategic intelligence rules
        
        Args:
            db: SQLAlchemy database session
            shop_id: Shop domain identifier
            product_text: Product text to match against
            limit: Maximum base chunks to return
        
        Returns:
            Dict with:
            - chunks: Vector similarity results
            - expanded_chunks: Entity-based expansion
            - related_triplets: Knowledge graph traversal results
            - strategic_rules: Strategic intelligence JSON
        """
        # Step 1: Standard vector similarity search
        base_chunks = await self.get_brand_context(
            db=db,
            shop_id=shop_id,
            product_text=product_text,
            limit=limit,
        )
        
        # Step 2: Extract entities mentioned in product text (simple keyword extraction)
        # For full entity extraction, would need IntelligenceExtractorService
        # For now, use a simple approach: look for entity tags in base chunks
        product_entities = []
        for chunk in base_chunks:
            entities = chunk.get("metadata", {}).get("entities", [])
            if isinstance(entities, list):
                product_entities.extend(entities)
        
        # Deduplicate
        product_entities = list(set(product_entities))[:10]  # Limit to top 10
        
        # Step 3: Find chunks that share entities (entity-based expansion)
        expanded_chunks = []
        if product_entities:
            expanded_chunks = await self._get_chunks_by_entities(
                db=db,
                shop_id=shop_id,
                entities=product_entities,
                exclude_ids=[],  # Could track chunk IDs if needed
                limit=3,
            )
        
        # Step 4: Traverse knowledge graph for related context
        related_triplets = []
        if product_entities:
            # Extract entity names (format: "type:name")
            entity_names = [e.split(":", 1)[-1] if ":" in e else e for e in product_entities]
            related_triplets = await self._traverse_knowledge_graph(
                db=db,
                shop_id=shop_id,
                seed_entities=entity_names,
                depth=2,  # 2 hops max
            )
        
        # Step 5: Get strategic intelligence
        strategic_intel = await self._get_strategic_intelligence(db, shop_id)
        
        return {
            "chunks": base_chunks,
            "expanded_chunks": expanded_chunks,
            "related_triplets": related_triplets,
            "strategic_rules": strategic_intel,
        }
    
    async def _get_chunks_by_entities(
        self,
        db: Session,
        shop_id: str,
        entities: List[str],
        exclude_ids: List[int],
        limit: int = 3,
    ) -> List[Dict]:
        """
        Find chunks that contain specified entities.
        
        Uses JSONB containment query on metadata_json.entities.
        
        Args:
            db: SQLAlchemy database session
            shop_id: Shop domain identifier
            entities: List of entity strings (format: "type:name" or just "name")
            exclude_ids: List of chunk IDs to exclude
            limit: Maximum results to return
        
        Returns:
            List of chunk dicts with content and metadata
        """
        if not entities:
            return []
        
        try:
            query = db.query(StoreContext).filter(
                StoreContext.shop_id == shop_id,
            )
            
            # Exclude specific IDs if provided
            if exclude_ids:
                query = query.filter(~StoreContext.id.in_(exclude_ids))
            
            # Filter chunks where entities array overlaps with our entities
            # PostgreSQL JSONB array containment
            entity_conditions = []
            for entity in entities[:5]:  # Limit to top 5 entities
                # Handle both "type:name" and "name" formats
                entity_key = entity.split(":", 1)[-1] if ":" in entity else entity
                # Check if metadata_json.entities array contains this entity
                # Using JSONB path operator
                entity_conditions.append(
                    StoreContext.metadata_json["entities"].astext.contains(entity_key)
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
                shop_id,
                e,
            )
            return []
    
    async def _traverse_knowledge_graph(
        self,
        db: Session,
        shop_id: str,
        seed_entities: List[str],
        depth: int = 2,
    ) -> List[Dict]:
        """
        Traverse knowledge graph from seed entities.
        
        Returns triplets connected to the seed entities within N hops.
        
        Args:
            db: SQLAlchemy database session
            shop_id: Shop domain identifier
            seed_entities: List of entity names to start from
            depth: Maximum number of hops to traverse
        
        Returns:
            List of triplet dicts with subject, relation, object, confidence
        """
        if not seed_entities or depth < 1:
            return []
        
        visited = set()
        results = []
        current_level = seed_entities
        
        try:
            for hop in range(depth):
                if not current_level:
                    break
                
                # Find triplets where subject or object matches current entities
                triplets = (
                    db.query(BrandEntity)
                    .filter(
                        BrandEntity.shop_id == shop_id,
                        or_(
                            BrandEntity.subject.in_(current_level),
                            BrandEntity.object.in_(current_level),
                        )
                    )
                    .all()
                )
                
                next_level = []
                for t in triplets:
                    key = f"{t.subject}-{t.relation}-{t.object}"
                    if key not in visited:
                        visited.add(key)
                        results.append({
                            "subject": t.subject,
                            "subject_type": t.subject_type,
                            "relation": t.relation,
                            "object": t.object,
                            "object_type": t.object_type,
                            "confidence": float(t.confidence) if t.confidence else 1.0,
                        })
                        # Add both subject and object to next level for traversal
                        next_level.extend([t.subject, t.object])
                
                # Prepare next level, excluding already visited
                current_level = [e for e in next_level if e not in visited][:20]  # Limit expansion
            
            return results
        except Exception as e:
            logger.warning(
                "[RAGService] Knowledge graph traversal failed shop=%s err=%s",
                shop_id,
                e,
            )
            return []
    
    async def _get_strategic_intelligence(
        self,
        db: Session,
        shop_id: str,
    ) -> Optional[Dict]:
        """
        Get stored strategic intelligence for a shop.
        
        Args:
            db: SQLAlchemy database session
            shop_id: Shop domain identifier
        
        Returns:
            Strategic intelligence dict or None if not found
        """
        try:
            shop = db.query(Shop).filter(Shop.domain == shop_id).first()
            if not shop:
                return None
            
            strategic_intel = getattr(shop, "strategic_intelligence", None)
            if not strategic_intel:
                return None
            
            # Handle both string and dict formats
            if isinstance(strategic_intel, str):
                import json
                try:
                    return json.loads(strategic_intel)
                except Exception:
                    return None
            
            return strategic_intel if isinstance(strategic_intel, dict) else None
        except Exception as e:
            logger.warning(
                "[RAGService] Failed to get strategic intelligence shop=%s err=%s",
                shop_id,
                e,
            )
            return None
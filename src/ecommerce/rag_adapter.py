"""
ShopifyRAGAdapter - Domain-specific RAG storage adapter for Shopify.

Implements the ``RAGStorageAdapter`` protocol by querying Shopify-specific
DB models (``Shop``, ``BrandEntity``) that live outside ``agentic_core``.
"""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)


class ShopifyRAGAdapter:
    """
    RAG storage adapter that queries Shopify-specific models.

    Fulfils the ``RAGStorageAdapter`` protocol defined in
    ``src.agentic_core.interfaces``.
    """

    async def get_strategic_intelligence(
        self, db: Any, tenant_id: str,
    ) -> Optional[Dict]:
        """Return strategic intelligence JSON from Shop record."""
        try:
            from src.ecommerce.db.models import Shop

            shop = db.query(Shop).filter(Shop.domain == tenant_id).first()
            if not shop:
                return None

            strategic_intel = getattr(shop, "strategic_intelligence", None)
            if not strategic_intel:
                return None

            if isinstance(strategic_intel, str):
                try:
                    return json.loads(strategic_intel)
                except Exception:
                    return None

            return strategic_intel if isinstance(strategic_intel, dict) else None
        except Exception as e:
            logger.warning(
                "[ShopifyRAGAdapter] get_strategic_intelligence failed tenant=%s err=%s",
                tenant_id, e,
            )
            return None

    async def get_tenant_summary(
        self, db: Any, tenant_id: str,
    ) -> Optional[Dict]:
        """Return brand context summary from Shop record."""
        try:
            from src.ecommerce.db.models import Shop

            shop = db.query(Shop).filter(Shop.domain == tenant_id).first()
            if not shop:
                return None

            brand_context = getattr(shop, "brand_context", None)
            if not brand_context:
                return None

            if isinstance(brand_context, str):
                try:
                    return json.loads(brand_context)
                except Exception:
                    return None

            return brand_context if isinstance(brand_context, dict) else None
        except Exception as e:
            logger.warning(
                "[ShopifyRAGAdapter] get_tenant_summary failed tenant=%s err=%s",
                tenant_id, e,
            )
            return None

    async def traverse_knowledge_graph(
        self,
        db: Any,
        tenant_id: str,
        seed_entities: List[str],
        depth: int = 2,
    ) -> List[Dict]:
        """Traverse BrandEntity knowledge graph from seed entities."""
        if not seed_entities or depth < 1:
            return []

        try:
            from src.ecommerce.db.models import BrandEntity

            visited: set = set()
            results: List[Dict] = []
            current_level = seed_entities

            for _hop in range(depth):
                if not current_level:
                    break

                triplets = (
                    db.query(BrandEntity)
                    .filter(
                        BrandEntity.tenant_id == tenant_id,
                        or_(
                            BrandEntity.subject.in_(current_level),
                            BrandEntity.object.in_(current_level),
                        ),
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
                        next_level.extend([t.subject, t.object])

                current_level = [e for e in next_level if e not in visited][:20]

            return results
        except Exception as e:
            logger.warning(
                "[ShopifyRAGAdapter] traverse_knowledge_graph failed tenant=%s err=%s",
                tenant_id, e,
            )
            return []

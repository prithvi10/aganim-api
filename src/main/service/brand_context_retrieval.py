from time import perf_counter

from sqlalchemy.orm import Session

from src.main.db.db_models import StoreContext
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

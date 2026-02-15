"""
AgentMemoryService - Learning and memory system for agents.

Provides:
- Storage of user corrections for future learning
- Retrieval of learned preferences based on similarity
- Recording of successes and failures for improvement
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from src.shared.logging.logger import get_logger

logger = get_logger(__name__)


class AgentMemoryService:
    """
    Memory service for agent learning and preference retrieval.
    
    This enables the "100-day learning" system where agents improve
    based on user corrections over time.
    
    Usage:
        memory = AgentMemoryService(shop_id="my-shop.myshopify.com")
        
        # Get learned preferences
        rules = await memory.get_learned_preferences("Copywriter")
        
        # Record a user correction
        await memory.record_correction(
            agent_role="Copywriter",
            original_output="Generated text...",
            user_correction="Better text...",
            context={"product_id": "123"}
        )
    """

    def __init__(self, shop_id: str, db: Optional[Session] = None):
        self.shop_id = shop_id
        self.db = db

    async def get_learned_preferences(
        self,
        agent_role: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve learned preferences/rules for an agent role.
        
        Uses embedding similarity to find corrections relevant to
        the current context.
        
        Args:
            agent_role: The agent role (e.g., "Copywriter", "PriceScout")
            limit: Maximum number of rules to return
        
        Returns:
            List of learned preference dicts
        """
        if not self.db:
            return []

        try:
            from src.agentic_core.db.models import AgentCorrection
            
            # Query recent corrections for this shop and agent role
            corrections = (
                self.db.query(AgentCorrection)
                .filter(
                    AgentCorrection.shop_id == self.shop_id,
                    AgentCorrection.agent_role == agent_role,
                )
                .order_by(AgentCorrection.created_at.desc())
                .limit(limit)
                .all()
            )

            rules = []
            for correction in corrections:
                rules.append({
                    "original": correction.original_output,
                    "correction": correction.user_correction,
                    "rule": f"User prefers: {correction.user_correction[:100]}..." 
                            if len(correction.user_correction) > 100 
                            else f"User prefers: {correction.user_correction}",
                })

            return rules

        except Exception as e:
            # AgentCorrection table might not exist yet
            logger.debug(
                "[AgentMemory] get_learned_preferences failed shop=%s role=%s err=%s",
                self.shop_id,
                agent_role,
                e,
            )
            return []

    async def record_correction(
        self,
        agent_role: str,
        original_output: str,
        user_correction: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Record a user correction for future learning.
        
        Args:
            agent_role: The agent role that produced the output
            original_output: What the agent generated
            user_correction: What the user changed it to
            context: Additional context (product info, etc.)
        
        Returns:
            True if recorded successfully
        """
        if not self.db:
            logger.warning("[AgentMemory] No database session for recording correction")
            return False

        try:
            from src.agentic_core.db.models import AgentCorrection
            from src.agentic_core.rag.embedding import embed_texts
            import uuid

            # Generate embedding for the correction (for future similarity search)
            correction_text = f"{original_output}\n---\n{user_correction}"
            embeddings = embed_texts([correction_text])
            embedding = embeddings[0] if embeddings else None

            correction = AgentCorrection(
                id=uuid.uuid4().hex,
                shop_id=self.shop_id,
                agent_role=agent_role,
                original_output=original_output,
                user_correction=user_correction,
                embedding=embedding,
            )

            self.db.add(correction)
            self.db.commit()

            logger.info(
                "[AgentMemory] Recorded correction shop=%s role=%s",
                self.shop_id,
                agent_role,
            )
            return True

        except Exception as e:
            logger.warning(
                "[AgentMemory] Failed to record correction shop=%s role=%s err=%s",
                self.shop_id,
                agent_role,
                e,
            )
            try:
                self.db.rollback()
            except Exception:
                pass
            return False

    async def record_success(
        self,
        agent_role: str,
        input_summary: str,
        output_summary: str,
    ) -> None:
        """
        Record a successful agent execution (for metrics/analytics).
        """
        logger.debug(
            "[AgentMemory] Success shop=%s role=%s input=%s output=%s",
            self.shop_id,
            agent_role,
            input_summary[:50],
            output_summary[:50],
        )

    async def record_failure(
        self,
        agent_role: str,
        tool_name: str,
        error: Optional[str],
    ) -> None:
        """
        Record an agent failure (for debugging/monitoring).
        """
        logger.warning(
            "[AgentMemory] Failure shop=%s role=%s tool=%s err=%s",
            self.shop_id,
            agent_role,
            tool_name,
            error,
        )

    async def get_similar_corrections(
        self,
        agent_role: str,
        query_text: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Find corrections similar to the current context using embeddings.
        """
        if not self.db:
            return []

        try:
            from src.agentic_core.db.models import AgentCorrection
            from src.agentic_core.rag.embedding import embed_texts

            # Generate query embedding
            embeddings = embed_texts([query_text])
            if not embeddings:
                return []
            query_vec = embeddings[0]

            # Search by embedding similarity
            corrections = (
                self.db.query(AgentCorrection)
                .filter(
                    AgentCorrection.shop_id == self.shop_id,
                    AgentCorrection.agent_role == agent_role,
                )
                .order_by(AgentCorrection.embedding.cosine_distance(query_vec))
                .limit(limit)
                .all()
            )

            return [
                {
                    "original": c.original_output,
                    "correction": c.user_correction,
                }
                for c in corrections
            ]

        except Exception as e:
            logger.debug(
                "[AgentMemory] get_similar_corrections failed shop=%s err=%s",
                self.shop_id,
                e,
            )
            return []

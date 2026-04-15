"""
ServiceRegistry - Dependency injection container for services.

Provides a centralized registry of services that agents receive via injection.
The generic registry knows about LLMService, SerpService, RAGService.
Domain-specific wiring (Shopify publish adapter, usage callbacks) is done
by factory methods in the ecommerce layer or by callers passing them in.

IMPORTANT: This module must NOT import from ``src.main`` or ``src.ecommerce``.
"""

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from .llm.llm_service import LLMService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _lazy_serp():
    from src.agentic_core.tools.serp_service import SerpService
    return SerpService


def _lazy_rag():
    from src.agentic_core.rag.rag_service import RAGService
    return RAGService


@dataclass
class ServiceRegistry:
    """
    Container for all services - injected into agents.

    Agents access services via:
        self.services.llm.generate_text(...)
        self.services.serp.search(...)
        self.services.rag.get_brand_context(...)
        self.services.publish_adapter.publish_product_body(...)
    """

    llm: Any  # LLMService
    serp: Any  # SerpService
    rag: Any  # RAGService
    publish_adapter: Optional[Any] = None  # PublishAdapter protocol

    @classmethod
    def create_default(
        cls,
        db: Optional["Session"] = None,
        shop_domain: Optional[str] = None,
        *,
        usage_callback: Optional[Callable] = None,
        publish_adapter: Optional[Any] = None,
        rag_adapter: Optional[Any] = None,
    ) -> "ServiceRegistry":
        """
        Factory method to create registry with default configuration.

        Accepts optional domain-specific adapters/callbacks that are
        injected by the domain layer (e.g. the Shopify shim overrides
        this method to auto-wire Shopify adapters).

        Parameters
        ----------
        db : Session, optional
            Database session for usage tracking.
        shop_domain : str, optional
            Tenant identifier for usage tracking.
        usage_callback : callable, optional
            Called with LLM usage dicts for cost tracking.
        publish_adapter : any, optional
            Adapter for autonomous publishing.
        rag_adapter : any, optional
            Adapter for domain-specific RAG storage queries.
        """
        SerpService = _lazy_serp()
        RAGService = _lazy_rag()

        return cls(
            llm=LLMService(
                api_key=os.getenv("OPENAI_API_KEY"),
                db=db,
                shop_domain=shop_domain,
                usage_callback=usage_callback,
            ),
            serp=SerpService(api_key=os.getenv("SERP_API_KEY")),
            rag=RAGService(storage_adapter=rag_adapter),
            publish_adapter=publish_adapter,
        )

    @classmethod
    def create_generic(
        cls,
        api_key: Optional[str] = None,
        serp_api_key: Optional[str] = None,
    ) -> "ServiceRegistry":
        """
        Factory method for generic (non-Shopify) usage.

        No usage_callback, no publish_adapter.
        """
        SerpService = _lazy_serp()
        RAGService = _lazy_rag()

        return cls(
            llm=LLMService(api_key=api_key or os.getenv("OPENAI_API_KEY")),
            serp=SerpService(api_key=serp_api_key or os.getenv("SERP_API_KEY")),
            rag=RAGService(),
            publish_adapter=None,
        )

    @classmethod
    def create_for_testing(
        cls,
        llm: Optional[Any] = None,
        serp: Optional[Any] = None,
        rag: Optional[Any] = None,
        publish_adapter: Optional[Any] = None,
    ) -> "ServiceRegistry":
        """
        Factory method for testing with mock services.
        """
        return cls(
            llm=llm or LLMService(),
            serp=serp or _lazy_serp()(),
            rag=rag or _lazy_rag()(),
            publish_adapter=publish_adapter,
        )

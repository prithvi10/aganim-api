"""
ServiceRegistry - Dependency injection container for services.

Provides a centralized registry of services that agents receive via injection.
"""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .llm_service import LLMService
from .serp_service import SerpService
from .rag_service import RAGService
from .meta_service import MetaService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class ServiceRegistry:
    """
    Container for all services - injected into agents.
    
    Agents access services via:
        self.services.llm.generate_text(...)
        self.services.serp.search(...)
        self.services.rag.get_brand_context(...)
    
    Usage:
        # Create with default configuration
        services = ServiceRegistry.create_default()
        
        # Create with db/shop for usage tracking
        services = ServiceRegistry.create_default(db=session, shop_domain="my-shop.myshopify.com")
        
        # Create with custom services (for testing)
        services = ServiceRegistry(
            llm=mock_llm_service,
            serp=mock_serp_service,
            rag=mock_rag_service,
        )
        
        # Inject into agent
        agent = RewriterAgent(shop_id="my-shop.myshopify.com", services=services)
    """
    
    llm: LLMService
    serp: SerpService
    rag: RAGService
    meta: Optional[MetaService] = None
    # Future services can be added here:
    # shopify: ShopifyService
    # analytics: AnalyticsService
    # etc.

    @classmethod
    def create_default(
        cls,
        db: Optional["Session"] = None,
        shop_domain: Optional[str] = None,
    ) -> "ServiceRegistry":
        """
        Factory method to create registry with default configuration.
        
        Reads API keys from environment variables.
        
        Args:
            db: Optional SQLAlchemy session for usage tracking
            shop_domain: Optional shop domain for usage tracking
        
        Returns:
            ServiceRegistry with all services configured
        """
        return cls(
            llm=LLMService(
                api_key=os.getenv("OPENAI_API_KEY"),
                db=db,
                shop_domain=shop_domain,
            ),
            serp=SerpService(api_key=os.getenv("SERP_API_KEY")),
            rag=RAGService(),
            meta=MetaService(),
        )

    @classmethod
    def create_for_testing(
        cls,
        llm: Optional[LLMService] = None,
        serp: Optional[SerpService] = None,
        rag: Optional[RAGService] = None,
    ) -> "ServiceRegistry":
        """
        Factory method for testing with mock services.
        
        Any service not provided will use a default instance.
        
        Args:
            llm: Optional mock LLMService
            serp: Optional mock SerpService
            rag: Optional mock RAGService
        
        Returns:
            ServiceRegistry with provided or default services
        """
        return cls(
            llm=llm or LLMService(),
            serp=serp or SerpService(),
            rag=rag or RAGService(),
        )

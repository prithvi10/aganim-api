# Backward-compat shim — canonical location: src/agentic_core/registry.py
#
# This shim patches ServiceRegistry.create_default to auto-wire
# Shopify-specific adapters (publish_adapter, rag_adapter, usage_callback).
from src.agentic_core.registry import *  # noqa: F401,F403
from src.agentic_core.registry import ServiceRegistry  # noqa: F401 - explicit

import os
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# --------------------------------------------------------------------------
# Shopify-specific adapter factories
# --------------------------------------------------------------------------

def _build_usage_callback(db: "Session", shop_domain: str) -> Optional[Callable]:
    """Build a usage callback that records LLM costs to fair_use_service."""
    try:
        from src.main.services.fair_use_service import record_cost_from_usage

        def _cb(usage_dict: dict) -> None:
            model = usage_dict.pop("model", "gpt-4o")
            record_cost_from_usage(
                db=db,
                shop_domain=shop_domain,
                usage=usage_dict,
                model_used=model,
            )

        return _cb
    except ImportError:
        return None


def _build_shopify_publish_adapter():
    """Lazily import and instantiate ShopifyPublishAdapter."""
    try:
        from src.main.ecommerce.publish_adapters import ShopifyPublishAdapter
        return ShopifyPublishAdapter()
    except ImportError:
        return None


def _build_shopify_rag_adapter():
    """Lazily import and instantiate ShopifyRAGAdapter."""
    try:
        from src.main.ecommerce.rag_adapter import ShopifyRAGAdapter
        return ShopifyRAGAdapter()
    except ImportError:
        return None


# --------------------------------------------------------------------------
# Override create_default with Shopify wiring
# --------------------------------------------------------------------------

_generic_create_default = ServiceRegistry.create_default.__func__


@classmethod  # type: ignore[misc]
def _shopify_create_default(
    cls,
    db: Optional["Session"] = None,
    shop_domain: Optional[str] = None,
    *,
    usage_callback: Optional[Callable] = None,
    publish_adapter: Optional[Any] = None,
    rag_adapter: Optional[Any] = None,
) -> ServiceRegistry:
    """
    Shopify-configured create_default.

    Auto-wires usage_callback, publish_adapter, and rag_adapter
    unless they are explicitly provided by the caller.
    """
    if usage_callback is None and db and shop_domain:
        usage_callback = _build_usage_callback(db, shop_domain)
    if publish_adapter is None:
        publish_adapter = _build_shopify_publish_adapter()
    if rag_adapter is None:
        rag_adapter = _build_shopify_rag_adapter()

    return _generic_create_default(
        cls,
        db=db,
        shop_domain=shop_domain,
        usage_callback=usage_callback,
        publish_adapter=publish_adapter,
        rag_adapter=rag_adapter,
    )


ServiceRegistry.create_default = _shopify_create_default
